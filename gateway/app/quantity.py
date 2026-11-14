"""plan_quantity: a need in L, kg or pieces becomes an order quantity in the API unit (PLAN M3.5, G-03).

Content per API unit is the 2-of-3 vote of F-01 (docs/data-and-api-findings.md):
* `api`: catalogPrice / comparisonPrice from /price, per the API unit (A-08, A-13), for shortlisted ids only;
* the static values from the catalogue (M2, D-06 steps 1-4: unit conversions, `units[]` KG, the parsed name), passed in
  as `StaticContent` so this module does not depend on catalog.db.

Two values agree within 5 %. When the API and a static value agree within 1 %, the static value wins (it removes the
cent rounding of the comparison price: 469119 gives 1.75 L, not 1.748). Without a majority the best single source is
used (the API first, D-06) and the plan needs a human review. Same-dimension values outside the majority are reported
as a conflict (X-23: 476738's comparison price is about 20 times off).

Rounding follows F-02: count units are whole numbers (a lot size of 0.01 would allow 571.43 bottles); KG-sold goods
round up to `allowedLotSize` steps; an exact stock amount caps the orderable quantity at a whole number of steps
(X-13: 43 kg in lots of 10 gives at most 40 kg).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Dim = Literal["L", "KG", "PCS"]
Confidence = Literal["high", "medium", "low"]

AGREE_TOLERANCE = Decimal("0.05")  # F-01: two sources agree within 5 %
SNAP_TOLERANCE = Decimal("0.01")  # F-01: API and static within 1 %: use the static value
OVERSHOOT_WARN_PCT = Decimal("10")
CASE_UNITS = ("KI", "CS", "KRT")  # full-case alternatives (F-02: 1,000 ST of 464306 = 50 KI of 20)
_EPS = Decimal("1e-9")
_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _ceil(x: Decimal) -> Decimal:
    nearest = x.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(x - nearest) < _EPS:  # 1000 / 1.0 must stay 1000, never 1001 through float noise
        return nearest
    return x.to_integral_value(rounding=ROUND_CEILING)


def _floor(x: Decimal) -> Decimal:
    nearest = x.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(x - nearest) < _EPS:
        return nearest
    return x.to_integral_value(rounding=ROUND_FLOOR)


def _norm(x: Decimal) -> Decimal:
    """Drop trailing zeros without switching to exponent notation (20.30 -> 20.3, 1000.00 -> 1000)."""
    q = x.normalize()
    return q.quantize(Decimal(1)) if q == q.to_integral_value() else q


# ---- inputs ---------------------------------------------------------------------------------


class StaticContent(BaseModel):
    """One static content value from the catalogue (M2): `value` `dim` per one `per_unit`."""

    model_config = ConfigDict(frozen=True)

    value: Decimal = Field(gt=0)
    dim: Dim
    per_unit: str  # the unit code the value describes, e.g. ST for "1 l" per bottle
    source: str = "static"  # e.g. unit_conversions, units_kg, sales_unit_kg, name
    confidence: Confidence = "medium"


class CatalogUnits(BaseModel):
    """The catalogue facts the planner and the offer normaliser need about one product."""

    model_config = ConfigDict(frozen=True)

    product_id: str
    sales_unit: str
    base_unit: str
    units: dict[str, Decimal] = Field(default_factory=dict)  # unitId -> sizeInBaseUnits
    allowed_lot_size: Decimal = Decimal("0.01")
    variable_unit: bool = False  # catch weight: invoiced by actual weight (Q-23)
    deposits: list[dict[str, Any]] = Field(default_factory=list)
    static_content: list[StaticContent] = Field(default_factory=list)

    @field_validator("units", mode="before")
    @classmethod
    def _units(cls, v: Any) -> Any:
        if isinstance(v, list):  # products.json shape: [{"unitId": "KI", "sizeInBaseUnits": 20.0}, ...]
            return {u["unitId"]: u.get("sizeInBaseUnits") or 1 for u in v if isinstance(u, dict) and u.get("unitId")}
        return v

    def size(self, unit: str | None) -> Decimal | None:
        """sizeInBaseUnits of a unit; the base unit is 1 even when units[] omits it."""
        if unit is None:
            return None
        if unit in self.units:
            return _dec(self.units[unit])
        return Decimal(1) if unit == self.base_unit else None

    @classmethod
    def from_product(cls, record: Mapping[str, Any], static_content: Iterable[StaticContent] = ()) -> CatalogUnits:
        """From a raw products.json record; the static content comes from the catalogue build (M2)."""
        synkka = record.get("synkkaData") or {}
        return cls(
            product_id=str(record.get("id") or record.get("productId")),
            sales_unit=record["salesUnit"],
            base_unit=record.get("baseUnit") or record["salesUnit"],
            units=record.get("units") or {},
            allowed_lot_size=_dec(record.get("allowedLotSize") or "0.01"),
            variable_unit=bool(synkka.get("variableUnit") or record.get("variableUnit")),
            deposits=list(record.get("deposits") or []),
            static_content=list(static_content),
        )


# ---- the content vote -----------------------------------------------------------------------


class ContentCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: Decimal  # per one API unit
    dim: Dim
    source: str  # api, unit_is_kg, units_pieces, or a StaticContent source
    confidence: Confidence
    raw: str | None = None  # how the value was derived, for the audit and the explanation


class ContentVote(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_unit: str
    value: Decimal | None  # content per API unit, None when unknown
    dim: Dim | None
    source: str | None  # "vote" when two sources agree, else the single source used
    confidence: Confidence | None
    needs_review: bool
    agreeing: list[str] = Field(default_factory=list)
    disagreeing: list[str] = Field(default_factory=list)
    candidates: list[ContentCandidate] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


def api_content(price_entry: Mapping[str, Any] | None) -> ContentCandidate | None:
    """catalogPrice / comparisonPrice to 0.001: L or KG per API unit (F-01). None without a comparison price."""
    if not price_entry or price_entry.get("error"):
        return None
    cat = (price_entry.get("catalogPrice") or {}).get("value")
    comp = (price_entry.get("comparisonPrice") or {}).get("value")
    unit = price_entry.get("comparisonUnit")
    if cat is None or not comp or unit not in ("L", "KG"):
        return None
    value = (_dec(cat) / _dec(comp)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if value <= 0:
        return None
    return ContentCandidate(value=value, dim=unit, source="api", confidence="high", raw=f"{cat} / {comp} per {unit}")


def _agree(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    return abs(a - b) <= tol * max(a, b)


def _priority(c: ContentCandidate) -> tuple[int, int]:
    return (1 if c.source == "api" else 0, _CONF_RANK[c.confidence])


def content_candidates(
    api_unit: str, catalog: CatalogUnits | None, price_entry: Mapping[str, Any] | None = None
) -> list[ContentCandidate]:
    """Every content value per API unit: the API's, then each static value converted through units[]."""
    out: list[ContentCandidate] = []
    api = api_content(price_entry)
    if api is not None:
        out.append(api)
    if catalog is None:
        return out
    target = catalog.size(api_unit)
    for s in catalog.static_content:
        own = catalog.size(s.per_unit)
        if target is None or own is None or own == 0:
            continue
        value = s.value * target / own
        raw = f"{_norm(s.value)} {s.dim} per {s.per_unit}"
        if s.per_unit != api_unit:
            raw += f", x {_norm(target / own)} {s.per_unit} per {api_unit}"
        out.append(ContentCandidate(value=value, dim=s.dim, source=s.source, confidence=s.confidence, raw=raw))
    if catalog.base_unit == "ST" and target is not None and not any(c.dim == "PCS" for c in out):
        # pieces per API unit straight from units[] (461051 Red Bull: KI = 24 ST)
        out.append(
            ContentCandidate(
                value=target,
                dim="PCS",
                source="units_pieces",
                confidence="high",
                raw=f"{_norm(target)} ST per {api_unit}",
            )
        )
    return out


def vote_content(
    api_unit: str,
    catalog: CatalogUnits | None,
    price_entry: Mapping[str, Any] | None = None,
    *,
    dim: Dim | None = None,
) -> ContentVote:
    """The F-01 vote, restricted to `dim` when candidates of that dimension exist."""
    if api_unit == "KG":
        one = ContentCandidate(value=Decimal(1), dim="KG", source="unit_is_kg", confidence="high", raw="sold per kg")
        return ContentVote(
            api_unit=api_unit, value=Decimal(1), dim="KG", source="unit_is_kg", confidence="high",
            needs_review=False, agreeing=["unit_is_kg"], candidates=[one],
        )  # fmt: skip
    candidates = content_candidates(api_unit, catalog, price_entry)
    pool = [c for c in candidates if dim is None or c.dim == dim] or candidates
    if not pool:
        return ContentVote(
            api_unit=api_unit, value=None, dim=None, source=None, confidence=None, needs_review=True,
            candidates=candidates, flags=["CONTENT_UNKNOWN"],
        )  # fmt: skip

    def cluster(c: ContentCandidate) -> list[ContentCandidate]:
        return [o for o in pool if o.dim == c.dim and _agree(c.value, o.value, AGREE_TOLERANCE)]

    best = max(pool, key=lambda c: (len(cluster(c)), _priority(c)))
    group = cluster(best)
    same_dim = [c for c in pool if c.dim == best.dim]
    outside = [c for c in same_dim if c not in group]
    flags: list[str] = []
    if len(group) >= 2:
        api = next((c for c in group if c.source == "api"), None)
        statics = sorted((c for c in group if c.source != "api"), key=_priority, reverse=True)
        if api is not None:
            close = [s for s in statics if _agree(api.value, s.value, SNAP_TOLERANCE)]
            value = close[0].value if close else api.value
        else:
            value = statics[0].value
        needs_review = False
        source = "vote"
        confidence: Confidence = "high"
    else:
        best = max(pool, key=_priority)
        outside = [c for c in same_dim if c is not best]
        value, source, confidence = best.value, best.source, best.confidence
        needs_review = True
        group = [best]
        flags.append("CONTENT_UNCONFIRMED")
    if outside:
        flags.append("CONTENT_CONFLICT")
    return ContentVote(
        api_unit=api_unit,
        value=_norm(value),
        dim=best.dim,
        source=source,
        confidence=confidence,
        needs_review=needs_review,
        agreeing=[c.source for c in group],
        disagreeing=[c.source for c in outside],
        candidates=candidates,
        flags=flags,
    )


# ---- the plan -------------------------------------------------------------------------------


class CaseAlternative(BaseModel):
    model_config = ConfigDict(frozen=True)

    unit: str
    cases: Decimal
    api_units_per_case: Decimal
    qty: Decimal  # in API units
    exact: bool  # the planned qty is already a whole number of cases


class QuantityPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    need_amount: Decimal
    need_unit: Dim
    api_unit: str
    catalog_unit: str | None
    content: ContentVote
    step: Decimal | None  # rounding step in API units
    qty: Decimal | None  # API units that cover the need, rounded up; None when it cannot be planned
    total_content: Decimal | None  # in need_unit
    overshoot: Decimal | None
    overshoot_pct: Decimal | None
    stock_kind: str | None = None
    max_orderable: Decimal | None = None  # only for an exact stock amount
    orderable_qty: Decimal | None = None
    shortfall: Decimal | None = None  # need_unit not covered by the orderable qty
    unit_price_net: Decimal | None = None
    total_net: Decimal | None = None
    price_per_content: Decimal | None = None  # EUR per need_unit, from the voted content (F-09)
    case_alternative: CaseAlternative | None = None
    flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_UNIT_ALIASES = {"L": "L", "LTR": "L", "LITRE": "L", "LITER": "L", "KG": "KG", "KGM": "KG", "PCS": "PCS", "KPL": "PCS"}


def _need_unit(unit: str) -> Dim:
    try:
        return _UNIT_ALIASES[unit.strip().upper()]  # type: ignore[return-value]
    except KeyError:
        raise ValueError(f"need unit must be L, KG or PCS, not {unit!r}") from None


def _api_unit_from(availability_entry: Mapping[str, Any] | None) -> str | None:
    lines = (availability_entry or {}).get("scheduleLines") or []
    return lines[0].get("salesUnit") if lines and isinstance(lines[0], dict) else None


def plan_quantity(
    need_amount: Decimal | float | int | str,
    need_unit: str,
    *,
    catalog: CatalogUnits | None,
    api_unit: str | None = None,
    price_entry: Mapping[str, Any] | None = None,
    availability_entry: Mapping[str, Any] | None = None,
    stock_kind: str | None = None,
    stock_qty: Decimal | float | int | None = None,
) -> QuantityPlan:
    """Units, rounding, overshoot and warnings for one product (G-03, F-01, F-02).

    The API unit comes from `api_unit`, else the availability line (A-08), else the catalogue sales unit (flagged).
    `stock_kind` and `stock_qty` are the offer's qtyKind and qty (normalise_offer); only an exact amount caps the plan.
    """
    need = _dec(need_amount)
    if need <= 0:
        raise ValueError("need amount must be positive")
    dim = _need_unit(need_unit)
    flags: list[str] = []
    warnings: list[str] = []

    unit = api_unit or _api_unit_from(availability_entry)
    if unit is None:
        if catalog is None:
            raise ValueError("no API unit: pass api_unit, an availability entry or the catalogue units")
        unit = catalog.sales_unit
        flags.append("UNIT_NOT_CONFIRMED")
        warnings.append(f"The API gave no unit; planned in the catalogue unit {unit}.")
    catalog_unit = catalog.sales_unit if catalog else None
    if catalog_unit and unit != catalog_unit:
        flags.append("UNIT_MISMATCH")

    vote = vote_content(unit, catalog, price_entry, dim=dim)
    flags.extend(f for f in vote.flags if f not in flags)
    if vote.needs_review:
        flags.append("NEEDS_REVIEW")
    if "CONTENT_CONFLICT" in vote.flags:
        others = [c for c in vote.candidates if c.source in vote.disagreeing]
        warnings.append(
            "Content sources disagree: "
            + "; ".join(f"{c.source} says {_norm(c.value)} {c.dim} per {unit}" for c in others)
            + (f"; used {vote.value} {vote.dim} ({vote.source})." if vote.value is not None else ".")
        )
    if "CONTENT_UNCONFIRMED" in vote.flags:
        warnings.append(f"Only one content source ({vote.source}); a person should confirm {vote.value} {vote.dim}.")

    lot = catalog.allowed_lot_size if catalog else Decimal("0.01")
    unit_price = None
    if price_entry and not price_entry.get("error"):
        cp = (price_entry.get("catalogPrice") or {}).get("value")
        unit_price = _dec(cp) if cp is not None else None

    content: Decimal | None
    step: Decimal | None
    qty: Decimal | None
    content, step, qty = vote.value, None, None
    if unit == "KG":
        if dim != "KG":
            flags.append("DIMENSION_MISMATCH")
            warnings.append(f"Sold per kg, but the need is in {dim}.")
            content = None
        else:
            step = lot if lot > Decimal("0.01") else Decimal("0.01")
            qty = _ceil(need / step) * step
    elif content is not None and vote.dim != dim:
        if dim == "PCS":
            flags.append("PCS_AS_ORDER_UNITS")
            warnings.append(f"No piece count per {unit}; read the need as {unit} order units.")
            content, step = Decimal(1), Decimal(1)
            qty = _ceil(need)
        else:
            flags.append("DIMENSION_MISMATCH")
            warnings.append(f"Content is known in {vote.dim}, but the need is in {dim}.")
            content = None
    elif content is None and dim == "PCS":
        flags.append("PCS_AS_ORDER_UNITS")
        content, step = Decimal(1), Decimal(1)
        qty = _ceil(need)
    elif content is not None:
        step = lot if lot > 1 else Decimal(1)
        qty = _ceil(need / content)
        if lot > 1:
            qty = _ceil(qty / lot) * lot

    if catalog and catalog.variable_unit:
        flags.append("CATCH_WEIGHT")
        warnings.append("Catch-weight product: invoiced by the actual weight delivered.")

    total = overshoot = overshoot_pct = None
    max_orderable = orderable = shortfall = None
    case_alt = None
    total_net = price_per_content = None
    if qty is not None and content is not None:
        qty = _norm(qty)
        total = _norm(qty * content)
        overshoot = _norm(total - need)
        overshoot_pct = (overshoot / need * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if overshoot_pct > OVERSHOOT_WARN_PCT:
            flags.append("OVERSHOOT")
            warnings.append(f"Rounding up to {qty} {unit} gives {total} {dim}, {overshoot_pct} % more than needed.")
        orderable = qty
        if stock_kind == "zero":
            max_orderable = orderable = Decimal(0)
        elif stock_kind == "exact" and stock_qty is not None and step is not None:
            amount = _dec(stock_qty)
            max_orderable = _norm(_floor(amount / step) * step)
            orderable = min(qty, max_orderable)
            if max_orderable < amount and orderable < qty:
                flags.append("LOT_SIZE_CAP")  # the lot step, not only the stock, limits the order (X-13)
        if orderable is not None and orderable < qty:
            flags.append("PARTIAL_STOCK")
            covered = orderable * content
            shortfall = _norm(max(need - covered, Decimal(0)))
            warnings.append(
                f"Only {max_orderable} {unit} can be ordered from stock ({_norm(covered)} {dim}); "
                f"{shortfall} {dim} needs another product."
            )
        if unit_price is not None:
            total_net = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if dim != "PCS" or vote.dim == "PCS":
                price_per_content = (unit_price / content).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        case_alt = _case_alternative(unit, qty, catalog)
    elif "DIMENSION_MISMATCH" not in flags:
        flags.append("CANNOT_PLAN")
        warnings.append(f"The content per {unit} is unknown, so the quantity cannot be planned.")

    if "UNIT_MISMATCH" in flags and content is not None:
        warnings.append(
            f"The API sells this in {unit} ({_norm(content)} {vote.dim or dim} each), "
            f"not in the catalogue unit {catalog_unit}."
        )
    return QuantityPlan(
        product_id=catalog.product_id if catalog else "",
        need_amount=need,
        need_unit=dim,
        api_unit=unit,
        catalog_unit=catalog_unit,
        content=vote,
        step=step,
        qty=qty,
        total_content=total,
        overshoot=overshoot,
        overshoot_pct=overshoot_pct,
        stock_kind=stock_kind,
        max_orderable=max_orderable,
        orderable_qty=orderable,
        shortfall=shortfall,
        unit_price_net=unit_price,
        total_net=total_net,
        price_per_content=price_per_content,
        case_alternative=case_alt,
        flags=_unique(flags),
        warnings=warnings,
    )


def _case_alternative(unit: str, qty: Decimal, catalog: CatalogUnits | None) -> CaseAlternative | None:
    if catalog is None or unit in CASE_UNITS:
        return None
    own = catalog.size(unit)
    for case in CASE_UNITS:
        size = catalog.size(case)
        if own and size and size > own:
            per_case = size / own
            cases = _ceil(qty / per_case)
            return CaseAlternative(
                unit=case,
                cases=_norm(cases),
                api_units_per_case=_norm(per_case),
                qty=_norm(cases * per_case),
                exact=cases * per_case == qty,
            )
    return None


def _unique(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))
