"""GS1 allergens, claims and labels from `synkkaData.classifications` (PLAN M2.2, findings D-04, D-08, S-05).

The rule this module exists for: missing data is `unknown`, never "free from". A record is `declared` for allergens
only when its `allergen` or `nonAllergen` group has at least one value; every minimal ERP record is `unknown`.
`allergen_status` answers per code with five values, and only an explicit FREE_FROM is "free_from".
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

AllergenStatus = Literal["contains", "may_contain", "free_from", "not_listed", "unknown"]
TemperatureClass = Literal["chilled", "frozen", "ambient", "unknown"]

LEVELS = ("CONTAINS", "MAY_CONTAIN", "UNDECLARED")
TEMPERATURE_LABELS = {"warmTemperature": "ambient", "coolTemperature": "chilled", "freezeTemperature": "frozen"}

# S-05: wheat, barley, rye and spelt CONTAINS imply cereals containing gluten; tree-nut sub-codes imply AN.
IMPLIES: dict[str, str] = {
    "UW": "AW",
    "GB": "AW",
    "NR": "AW",
    "GS": "AW",
    **{c: "AN" for c in ("SA", "SH", "SW", "SC", "SP", "SR", "SM", "ST")},
}
GLUTEN_CEREALS = frozenset({"AW", "UW", "GB", "NR", "GS"})
NO_DECLARABLE = "X99"  # "no declarable allergens", sometimes coded as CONTAINS (D-04); kept out of the code lists

# temperatureCondition (D-08, meanings inferred). 6 (cool to ambient) and 9 (mixed) are unclear, so unknown.
TEMPERATURE_CLASS: dict[int, TemperatureClass] = {
    1: "chilled",
    2: "chilled",
    3: "chilled",
    4: "chilled",
    5: "chilled",
    7: "frozen",
    8: "ambient",
}


@dataclass
class Decoded:
    contains: list[str] = field(default_factory=list)
    may_contain: list[str] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    free_from: list[str] = field(default_factory=list)
    implied_contains: list[str] = field(default_factory=list)  # parents implied by a CONTAINS sub-code, e.g. AW from UW
    no_declarable_allergens: bool = False  # X99 present
    allergen_data: Literal["declared", "unknown"] = "unknown"
    claims: list[str] = field(default_factory=list)
    claim_data: Literal["declared", "unknown"] = "unknown"
    labels: list[str] = field(default_factory=list)  # quality, origin and eco labels; temperature labels excluded
    temperature_label: str | None = None  # chilled, frozen or ambient from the temperature label
    lactose_g_per_100: float | None = None  # LACS from nutritionalContent
    flags: list[str] = field(default_factory=list)

    @property
    def contains_effective(self) -> list[str]:
        """CONTAINS codes plus the parents they imply: the list a diet filter checks."""
        return sorted(set(self.contains) | set(self.implied_contains))

    def allergens_dict(self) -> dict[str, Any]:
        return {
            "contains": self.contains,
            "may_contain": self.may_contain,
            "undeclared": self.undeclared,
            "free_from": self.free_from,
            "implied_contains": self.implied_contains,
            "no_declarable_allergens": self.no_declarable_allergens,
        }


def _values(groups: Mapping[str, list[dict]], name: str) -> list[dict]:
    return groups.get(name) or []


def decode(synkka: Mapping[str, Any] | None) -> Decoded:
    """Decode one product's classifications (and LACS) into code lists, with data-quality flags."""
    out = Decoded()
    synkka = synkka or {}
    groups: dict[str, list[dict]] = {}
    for g in synkka.get("classifications") or []:
        groups.setdefault(g.get("name") or "", []).extend(g.get("values") or [])

    by_level: dict[str, set[str]] = {lv: set() for lv in LEVELS}
    for v in _values(groups, "allergen"):
        code, level = v.get("id"), v.get("unit")
        if not code:
            continue
        if code == NO_DECLARABLE:
            out.no_declarable_allergens = True
            continue
        by_level.setdefault(level or "CONTAINS", set()).add(code)
    free: set[str] = set()
    for v in _values(groups, "nonAllergen"):
        code = v.get("id")
        if code == NO_DECLARABLE:
            out.no_declarable_allergens = True
        elif code:
            free.add(code)

    contains = by_level["CONTAINS"]
    may = by_level["MAY_CONTAIN"] - contains
    if (contains | may) & free:
        # 468044, 469429 (D-04): the same code both present and free from. The presence wins.
        out.flags.append("allergen_code_conflict")
        free -= contains | may
    implied = {IMPLIES[c] for c in contains if c in IMPLIES} - contains
    if implied & free:
        out.flags.append("allergen_code_conflict")  # 467828: AW free from while UW CONTAINS
        free -= implied
    out.contains, out.may_contain = sorted(contains), sorted(may)
    out.undeclared = sorted(by_level["UNDECLARED"] - contains - may)
    out.free_from, out.implied_contains = sorted(free), sorted(implied)
    if contains or may or by_level["UNDECLARED"] or free or out.no_declarable_allergens:
        out.allergen_data = "declared"

    claims = {v["id"] for v in _values(groups, "nutritionalClaim") if v.get("id")}
    out.claims = sorted(claims)
    if claims:
        out.claim_data = "declared"

    labels: set[str] = set()
    for v in _values(groups, "packagingMarkedLabel"):
        code = v.get("id")
        if code in TEMPERATURE_LABELS:
            out.temperature_label = TEMPERATURE_LABELS[code]
        elif code:
            labels.add(code)
    out.labels = sorted(labels)

    for n in synkka.get("nutritionalContent") or []:
        if n.get("id") == "LACS" and isinstance(n.get("value"), int | float):
            out.lactose_g_per_100 = float(n["value"])
            break

    eff = set(out.contains_effective)
    if "FREE_FROM_LACTOSE" in claims and (out.lactose_g_per_100 or 0) > 0.01:
        out.flags.append("lactose_free_claim_with_lactose")  # 460050 (D-04)
    if "FREE_FROM_GLUTEN" in claims and eff & GLUTEN_CEREALS:
        out.flags.append("gluten_free_with_gluten_cereal")  # 460124: gluten-free wheat starch
    if "FREE_FROM_GLUTEN" in claims and "GO" in contains:
        out.flags.append("gluten_free_with_oats")
    if "VEGAN" in claims and eff & {"AM", "ML"}:
        out.flags.append("vegan_with_milk_code")  # Santa Maria spices (D-04)
    return out


def temperature_class(condition: int | None) -> TemperatureClass:
    return TEMPERATURE_CLASS.get(condition, "unknown") if condition is not None else "unknown"


def allergen_status(record: Mapping[str, Any], code: str) -> AllergenStatus:
    """One allergen code for one compact record.

    unknown: the record declares no allergen data at all (every minimal record), so nothing can be promised.
    not_listed: allergen data is declared but this code is not mentioned; S-05 accepts that for "exclude X".
    free_from: only an explicit nonAllergen FREE_FROM.
    """
    if record.get("allergen_data") != "declared":
        return "unknown"
    a = record.get("allergens") or {}
    if code in a.get("contains", ()) or code in a.get("implied_contains", ()):
        return "contains"
    if code in a.get("may_contain", ()):
        return "may_contain"
    if code in a.get("free_from", ()):
        return "free_from"
    return "not_listed"


def has_claim(record: Mapping[str, Any], claim: str) -> bool | None:
    """True for an explicit claim; None (unknown) when the record has no claim data; False otherwise.

    LOW_LACTOSE never satisfies FREE_FROM_LACTOSE: the codes are compared exactly.
    """
    if claim in (record.get("claims") or ()):
        return True
    return None if record.get("claim_data") != "declared" else False
