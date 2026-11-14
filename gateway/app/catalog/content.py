"""Static pack content per unit (PLAN M2.3, findings D-05..D-07, F-01).

Two static votes are kept apart, because M3.5 adds the third (the API comparison price) and takes 2 of 3:

- `static`, D-06 steps 1-3 in priority order:
  1. salesUnit KG is 1 kg per unit; baseUnit KG is `units[salesUnit].sizeInBaseUnits` kg (source `units`, high);
  2. `synkkaData.unitConversions[0]`, which describes the sales unit (D-07): `volume` in LTR/MLT/CLT gives litres,
     `netWeight` (or a `volume` in GRM/KGM) gives kg, `volume` in H87 gives pieces (source `unit_conversions`);
  3. a `units[]` entry KG gives 1 / sizeInBaseUnits kg per base unit (source `units`). ZML is never used (D-05).
- `name`, D-06 step 4: "12 x 1 l", "4x5 kg", "2,5 dl", "200/150g" (drained 150 g), "96kpl 80g", "M90" (90 eggs),
  read as the base unit's content unless the count matches a packaging level, then multiplied up to the sales unit.

The chosen value is the static one when it exists, else the name. Confidence:
- high: static and name agree within 5 %, or the unit is itself a kilogram;
- medium: one source only, or the two measure different things (litres against kilograms);
- low: they disagree (`content_conflict`, needs review: 464076 says 20 kg in unitConversions and 5 kg in its name),
  or the only value is a name that likely describes one item inside a case (463233 "voi 10 g" sold per KI).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Dim = Literal["L", "KG", "PCS"]
Source = Literal["units", "unit_conversions", "name"]
Confidence = Literal["high", "medium", "low"]

AGREE = 0.05  # F-01: two sources agree within 5 %
CASE_UNITS = frozenset({"KI", "CS", "KRT", "KLE", "DSP", "PAL"})  # units that normally hold several items (D-05)

_NAME_UNITS: dict[str, tuple[Dim, float]] = {
    "kg": ("KG", 1.0),
    "g": ("KG", 0.001),
    "gr": ("KG", 0.001),
    "l": ("L", 1.0),
    "ltr": ("L", 1.0),
    "dl": ("L", 0.1),
    "cl": ("L", 0.01),
    "ml": ("L", 0.001),
}
_GS1_LITRES = {"LTR": 1.0, "MLT": 0.001, "CLT": 0.01, "DLT": 0.1}
_GS1_KG = {"KGM": 1.0, "GRM": 0.001, "MGM": 0.000001}

_NUM = r"(\d+(?:[.,]\d+)?)"
_U = r"(kg|gr|g|ltr|l|dl|cl|ml)(?![a-zåäö0-9])"
_START = r"(?:(?<![\w.,])|(?<=\bn)|(?<=\bca))"  # "n2kg", "ca2kg": approximate weights
_MULTI = re.compile(rf"(?<![\w.,]){_NUM}\s*[x×*]\s*{_NUM}\s*{_U}")
_COUNT_SIZE = re.compile(rf"(?<![\w.,])(\d+)\s*(?:kpl|pcs|st|stk|ps)\.?\s+{_NUM}\s*{_U}")
_DRAINED = re.compile(rf"(?<![\w.,]){_NUM}\s*/\s*{_NUM}\s*(kg|g)(?![a-zåäö0-9])")
_SINGLE = re.compile(rf"{_START}{_NUM}\s*{_U}")
_COUNT = re.compile(r"(?<![\w.,])(\d+)\s*(?:kpl|pcs)(?![a-zåäö])")
_EGGS = re.compile(r"(?<![\w])(?:S|M|L|XL)(\d{2,3})(?![\w])")


def _num(s: str) -> float:
    return float(s.replace(",", "."))


@dataclass
class NameContent:
    value: float  # content of the item the name describes (a x b for a multipack), in `dim`
    dim: Dim
    kind: Literal["multipack", "drained", "single", "count", "eggs"]
    count: float | None = None  # a in "a x b"
    each: float | None = None  # b in "a x b"
    approximate: bool = False
    ambiguous: bool = False  # several different sizes in the name


def parse_name(name: str | None) -> NameContent | None:
    """The pack size a product name states, or None. Pure text; units are applied by `static_content`."""
    if not name:
        return None
    text = name.casefold()
    m = _MULTI.search(text) or _COUNT_SIZE.search(text)
    if m:
        dim, f = _NAME_UNITS[m.group(3)]
        a, b = _num(m.group(1)), _num(m.group(2)) * f
        if a > 0 and b > 0:
            return NameContent(a * b, dim, "multipack", count=a, each=b)
    m = _DRAINED.search(text)
    if m:
        dim, f = _NAME_UNITS[m.group(3)]
        return NameContent(_num(m.group(2)) * f, dim, "drained")  # 49 of 51 a/b names use the drained figure
    singles = [
        (_num(m.group(1)) * _NAME_UNITS[m.group(2)][1], _NAME_UNITS[m.group(2)][0], m) for m in _SINGLE.finditer(text)
    ]
    singles = [s for s in singles if s[0] > 0]
    if singles:
        value, dim, m = singles[0]
        approx = m.start() > 0 and text[max(0, m.start() - 2) : m.start()].endswith(("n", "ca"))
        distinct = {(round(v, 6), d) for v, d, _ in singles}
        return NameContent(value, dim, "single", approximate=approx, ambiguous=len(distinct) > 1)
    if "muna" in text:
        m = _EGGS.search(name)
        if m:
            return NameContent(float(m.group(1)), "PCS", "eggs")
    m = _COUNT.search(text)
    if m and int(m.group(1)) > 0:
        return NameContent(float(m.group(1)), "PCS", "count")
    return None


@dataclass
class Vote:
    value: float  # per sales unit
    dim: Dim
    source: Source
    detail: str
    per_base: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": _round(self.value),
            "dim": self.dim,
            "source": self.source,
            "detail": self.detail,
            "per_base": _round(self.per_base),
        }


@dataclass
class Content:
    unit: str  # the sales unit the value is for
    value: float | None
    dim: Dim | None
    source: Source | None
    confidence: Confidence | None
    needs_review: bool
    per_base: float | None  # content per base unit, so any packaging level can be computed (content_for_unit)
    static: Vote | None
    name: Vote | None
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "value": _round(self.value),
            "dim": self.dim,
            "source": self.source,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "per_base": _round(self.per_base),
            "static": self.static.as_dict() if self.static else None,
            "name": self.name.as_dict() if self.name else None,
            "flags": self.flags,
            "notes": self.notes,
        }


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 6)


def _sizes(units: list[Mapping[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for u in units:
        uid, size = u.get("unitId"), u.get("sizeInBaseUnits")
        if uid and isinstance(size, int | float) and size > 0 and uid not in out:
            out[uid] = float(size)
    return out


def _measure(q: Mapping[str, Any] | None, table: Mapping[str, float]) -> float | None:
    if not q or q.get("unit") not in table or not isinstance(q.get("value"), int | float) or q["value"] <= 0:
        return None
    return float(q["value"]) * table[q["unit"]]


def _conversion_candidates(level: Mapping[str, Any]) -> list[tuple[Dim, float, str]]:
    """(dim, value, field) candidates from one unitConversions level, in default preference order."""
    out: list[tuple[Dim, float, str]] = []
    vol = level.get("volume")
    litres = _measure(vol, _GS1_LITRES)
    if litres:
        out.append(("L", litres, "volume"))
    net = _measure(level.get("netWeight"), _GS1_KG)
    if net:
        out.append(("KG", net, "netWeight"))
    vol_kg = _measure(vol, _GS1_KG)  # D-07: volume behaves like GS1 net content in any unit
    if vol_kg:
        out.append(("KG", vol_kg, "volume"))
    if vol and vol.get("unit") == "H87" and isinstance(vol.get("value"), int | float) and vol["value"] > 0:
        out.append(("PCS", float(vol["value"]), "volume"))
    return out


def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b))


def static_content(product: Mapping[str, Any], name_fi: str | None) -> Content:
    """Content per sales unit from the raw product, with both votes, flags and a confidence."""
    sales, base = product.get("salesUnit") or "", product.get("baseUnit") or ""
    sizes = _sizes(product.get("units") or [])
    sales_size = sizes.get(sales, 1.0 if sales == base else None)
    synkka = product.get("synkkaData") or {}
    flags: list[str] = []
    notes: list[str] = []

    parsed = parse_name(name_fi)
    name_vote: Vote | None = None
    if parsed and sales != "KG" and sales_size:
        per_base = parsed.value
        detail = f"{parsed.kind} {parsed.value:g} {parsed.dim}"
        if parsed.kind == "multipack" and parsed.count and parsed.each:
            level = next((u for u, s in sizes.items() if u != base and abs(s - parsed.count) < 1e-9), None)
            if level:
                per_base = parsed.each  # "4x5 kg" with KI = 4 ST: one ST is 5 kg
                detail = f"{parsed.count:g} x {parsed.each:g} {parsed.dim}, count matches {level}"
        name_vote = Vote(per_base * sales_size, parsed.dim, "name", detail, per_base)
        if parsed.approximate:
            notes.append("name states an approximate weight")
        if parsed.kind == "drained":
            notes.append("name states net/drained weight; the drained figure is used")
    elif parsed and sales == "KG":
        notes.append("sold per kilogram: the name's size describes one piece")

    static: Vote | None = None
    exact = sales == "KG" or (base == "KG" and bool(sales_size))  # step 1: the unit is itself kilograms
    if sales == "KG":
        static = Vote(1.0, "KG", "units", "sales unit KG", 1.0 / (sales_size or 1.0))
    elif base == "KG" and sales_size:
        static = Vote(sales_size, "KG", "units", f"base unit KG, {sales} = {sales_size:g} KG", 1.0)
    else:
        levels = synkka.get("unitConversions") or []
        cands = _conversion_candidates(levels[0]) if levels else []
        if cands and sales_size:
            pick = cands[0]
            if name_vote:
                same = [c for c in cands if c[0] == name_vote.dim]
                if same:
                    pick = min(same, key=lambda c: _rel(c[1], name_vote.value))
            elif any(c[0] != "PCS" for c in cands):
                pick = next(c for c in cands if c[0] != "PCS")
            dim, value, fld = pick
            ptype = levels[0].get("synkkaPackagingType") or "?"
            static = Vote(
                value, dim, "unit_conversions", f"{ptype} {fld} {value:g} {dim} for {sales}", value / sales_size
            )
            gtin = synkka.get("gtin")
            # D-07: when the Synkka GTIN sits on a level that is neither the base nor the sales unit, the
            # conversion may describe that level instead (32-33 products, 464076).
            other = next(
                (
                    u.get("unitId")
                    for u in product.get("units") or []
                    if gtin and u.get("gtin") == gtin and u.get("unitId") not in (sales, base)
                ),
                None,
            )
            if other and sizes.get(other):
                alt = value * sales_size / sizes[other]
                flags.append("unit_conversions_unit_ambiguous")
                notes.append(
                    f"the Synkka GTIN is on {other}: unitConversions may describe {other} ({alt:g} {dim} per {sales})"
                )
        elif "KG" in sizes and sales_size:
            per_base = 1.0 / sizes["KG"]
            static = Vote(per_base * sales_size, "KG", "units", f"units[] KG = {sizes['KG']:g} {base}", per_base)

    chosen = static or name_vote
    confidence: Confidence | None = None
    needs_review = False
    if static and name_vote:
        if static.dim == name_vote.dim:
            if _rel(static.value, name_vote.value) <= AGREE:
                confidence = "high"
            else:
                confidence, needs_review = "low", True
                flags.append("content_conflict")
        else:
            confidence = "medium"
            flags.append("content_dimension_mismatch")
    elif static:
        confidence = "high" if exact else "medium"
    elif name_vote and parsed:
        confidence = "medium"
        one_item = parsed.kind in ("single", "drained") and sales in CASE_UNITS and sales == base
        if one_item:
            flags.append("name_may_describe_one_item")  # 463233 "voi 10 g" per KI is really 2.1 kg (D-06)
        if one_item or parsed.ambiguous:
            confidence = "low"
            needs_review = True
    if chosen is None:
        flags.append("content_unknown")
    elif parsed and parsed.ambiguous:
        notes.append("the name states several sizes; the first is used")

    # Packaging far heavier than the content: the value probably describes one item, not the unit.
    gross = None
    levels = synkka.get("unitConversions") or []
    if levels:
        gross = _measure(levels[0].get("grossWeight"), _GS1_KG)
    if chosen and not exact and gross and chosen.dim in ("KG", "L") and chosen.value < gross * 0.1:
        flags.append("content_far_below_gross_weight")
        confidence, needs_review = "low", True

    return Content(
        unit=sales,
        value=chosen.value if chosen else None,
        dim=chosen.dim if chosen else None,
        source=chosen.source if chosen else None,
        confidence=confidence,
        needs_review=needs_review,
        per_base=chosen.per_base if chosen else None,
        static=static,
        name=name_vote,
        flags=flags,
        notes=notes,
    )
