"""Offer normaliser: raw /availability and /price entries become one typed offer per line (PLAN M3.3, M3.4, G-04).

Rules from docs/data-and-api-findings.md:
* the unit is the availability line's `salesUnit`, which is the unit of both the price and the amount (A-08);
* amounts are classified per F-03: Terminal quantities are unknown, placeholder amounts (A-05) are "not tracked" and
  never shown as a number, zero is out of stock, anything else is a real amount;
* feasibility follows F-04 in order: unknown id, not deliverable, sales block, out of stock, late, cut-off, partial;
* cut-offs are compared with an injectable as-of clock in Europe/Helsinki (M3.3, X-06), with an approval buffer;
* a need date after the snapshot's `availableDate` gets an estimated cut-off with the same lead time, not the stale one
  (A-03, F-05, X-05);
* price validity uses Helsinki local dates of validFrom and validTo, validTo inclusive (A-09, F-07).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.clients.valio import check_product_id
from app.quantity import CatalogUnits

if TYPE_CHECKING:
    from app.clients.valio import ApiResult

# ---- the as-of clock (M3.3) -----------------------------------------------------------------


class _EuHelsinki(tzinfo):
    """Fallback when the system has no tz database: EET/EEST with the EU switch (last Sunday of March and October,
    01:00 UTC). Only used if ZoneInfo('Europe/Helsinki') is unavailable."""

    @staticmethod
    def _last_sunday(year: int, month: int) -> datetime:
        d = datetime(year, month + 1, 1, 1, tzinfo=UTC) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    def _is_dst_utc(self, utc: datetime) -> bool:
        return self._last_sunday(utc.year, 3) <= utc < self._last_sunday(utc.year, 10)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(hours=2)
        wall = dt.replace(tzinfo=UTC)
        as_summer = self._is_dst_utc(wall - timedelta(hours=3))
        as_winter = self._is_dst_utc(wall - timedelta(hours=2))
        if as_summer and not as_winter:  # the repeated hour in October (PEP 495 fold)
            return timedelta(hours=2 if dt.fold else 3)
        if as_winter and not as_summer:  # the skipped hour in March
            return timedelta(hours=3 if dt.fold else 2)
        return timedelta(hours=3) if as_summer else timedelta(hours=2)

    def dst(self, dt: datetime | None) -> timedelta:
        return self.utcoffset(dt) - timedelta(hours=2)

    def tzname(self, dt: datetime | None) -> str:
        return "EEST" if self.dst(dt) else "EET"

    def fromutc(self, dt: datetime) -> datetime:
        utc = dt.replace(tzinfo=UTC)
        dst = self._is_dst_utc(utc)
        fold = int(not dst and self._is_dst_utc(utc - timedelta(hours=1)))  # second pass of the repeated hour
        return (dt + timedelta(hours=3 if dst else 2)).replace(tzinfo=self, fold=fold)


try:
    HELSINKI: tzinfo = ZoneInfo("Europe/Helsinki")
except ZoneInfoNotFoundError:  # pragma: no cover - slim images without tzdata
    HELSINKI = _EuHelsinki()

Clock = Callable[[], datetime]


def parse_api_time(value: str) -> datetime:
    """`2026-11-15T17:00:00+0200` (A-16), also with a colon offset or the pre-1921 `+013949`. Naive means Helsinki."""
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=HELSINKI)


def to_helsinki(dt: datetime) -> datetime:
    return dt.replace(tzinfo=HELSINKI) if dt.tzinfo is None else dt.astimezone(HELSINKI)


def local_date(value: str | datetime) -> date:
    """The Europe/Helsinki calendar date of an API timestamp (validTo 2026-12-31T00:00:00+0200 is 2026-12-31)."""
    dt = parse_api_time(value) if isinstance(value, str) else value
    return to_helsinki(dt).date()


def fixed_clock(as_of: str | datetime) -> Clock:
    """A clock frozen at `as_of`, for the demo badge and for tests."""
    instant = to_helsinki(parse_api_time(as_of) if isinstance(as_of, str) else as_of)
    return lambda: instant


def system_clock() -> Clock:
    return lambda: datetime.now(HELSINKI)


def clock_from_settings(settings: Any = None) -> Clock:
    """The AS_OF setting when set (the demo clock), else the system clock."""
    if settings is None:
        from app.settings import get_settings

        settings = get_settings()
    as_of = (getattr(settings, "as_of", None) or "").strip()
    return fixed_clock(as_of) if as_of else system_clock()


def _now(as_of: datetime | Clock) -> datetime:
    return to_helsinki(as_of() if callable(as_of) else as_of)


# ---- the typed offer ------------------------------------------------------------------------

QtyKind = Literal["exact", "untracked", "terminal", "zero", "none"]
Feasibility = Literal[
    "orderable",
    "unknown_id",
    "not_deliverable",
    "sales_blocked",
    "out_of_stock",
    "late",
    "cutoff_passed",
    "cutoff_too_close",
    "partial",
]
Validity = Literal["valid", "not_valid_for_delivery_date", "no_price", "unknown"]

UNTRACKED_TOTAL = 9_999_999_999  # A-05: placeholder = floor(9,999,999,999 / sizeInBaseUnits of the API unit)
UNTRACKED_FLOOR = 1_000_000  # F-03 safety net: largest real amount seen 68,293, smallest placeholder 24,999,999
DEEP_DISCOUNT_PCT = Decimal("50")
DEFAULT_BUFFER = timedelta(hours=1)  # F-04: time for a human approval and the submit


class _Camel(BaseModel):
    model_config = ConfigDict(frozen=True, alias_generator=to_camel, populate_by_name=True)


class OfferPrice(_Camel):
    """Per API unit, EUR. `net` is catalogPrice.value (excl. VAT), `gross` its valueWithTax (A-10)."""

    net: Decimal
    gross: Decimal | None = None
    list_price: Decimal | None = None
    tax_rate: Decimal | None = None
    currency: str = "EUR"
    net_price_found: bool = False
    comparison_price: Decimal | None = None
    comparison_unit: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    discount_pct: Decimal | None = None  # 1 - net / list, never negative (F-08)


class NormalisedOffer(_Camel):
    product_id: str
    unit: str | None  # the API unit (scheduleLines[].salesUnit), else the catalogue unit (unit_source says which)
    unit_source: Literal["api", "catalog"] | None = None
    catalog_unit: str | None = None
    qty_kind: QtyKind
    qty: Decimal | None  # only for exact (and 0 for zero); never a placeholder
    logistic_model: str | None = None
    available_date: date | None = None
    need_date: date | None = None
    late_days: int | None = None
    order_by: datetime | None = None  # Helsinki
    order_by_estimated: bool = False
    approve_by: datetime | None = None  # order_by minus the buffer
    cutoff_passed: bool = False
    blocked: bool = False
    feasibility: Feasibility
    price: OfferPrice | None = None
    validity: Validity
    flags: list[str] = Field(default_factory=list)
    as_of: datetime
    evidence: list[str] = Field(default_factory=list)  # sha256 of the raw responses behind this offer


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def classify_amount(
    amount: Any, logistic_model: str | None, api_unit: str | None, catalog: CatalogUnits | None = None
) -> tuple[QtyKind, Decimal | None]:
    """F-03 for one availability line."""
    if logistic_model == "Terminal":
        return "terminal", None
    value = _dec(amount)
    if value is None:
        return "none", None
    if value == 0:
        return "zero", Decimal(0)
    size = catalog.size(api_unit) if catalog else None
    if value >= UNTRACKED_FLOOR or (size and value == int(Decimal(UNTRACKED_TOTAL) / size)):
        return "untracked", None
    return "exact", value


def _price(entry: Mapping[str, Any]) -> OfferPrice | None:
    cat = entry.get("catalogPrice") or {}
    if entry.get("error") or cat.get("value") is None:
        return None
    net = _dec(cat["value"])
    lst = _dec((entry.get("listPrice") or {}).get("value"))
    discount = None
    if lst and net is not None and lst > 0 and net <= lst:
        discount = ((1 - net / lst) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    comp = entry.get("comparisonPrice") or {}
    return OfferPrice(
        net=net,
        gross=_dec(cat.get("valueWithTax")),
        list_price=lst,
        tax_rate=_dec((entry.get("tax") or {}).get("taxRate")),
        currency=cat.get("currency") or "EUR",
        net_price_found=bool(entry.get("netPriceFound")),
        comparison_price=_dec(comp.get("value")),
        comparison_unit=entry.get("comparisonUnit"),
        valid_from=local_date(cat["validFrom"]) if cat.get("validFrom") else None,
        valid_to=local_date(cat["validTo"]) if cat.get("validTo") else None,
        discount_pct=discount,
    )


def normalise_offer(
    product_id: str,
    availability: Mapping[str, Any] | None,
    price: Mapping[str, Any] | None,
    *,
    as_of: datetime | Clock,
    need_date: date | str | None = None,
    catalog: CatalogUnits | None = None,
    qty_needed: Decimal | float | int | None = None,
    buffer: timedelta = DEFAULT_BUFFER,
    evidence: Iterable[str] = (),
) -> NormalisedOffer:
    """One typed offer from one /availability entry and one /price entry.

    `qty_needed` is in API units (from plan_quantity); with an exact amount below it the offer is `partial`.
    """
    now = _now(as_of)
    need = date.fromisoformat(need_date) if isinstance(need_date, str) else need_date
    flags: list[str] = []
    checked = check_product_id(product_id)
    pid = checked if isinstance(checked, str) else str(product_id)
    valid_id = isinstance(checked, str)

    entry = availability or {}
    lines = [ln for ln in entry.get("scheduleLines") or [] if isinstance(ln, dict)]
    line = lines[0] if lines else None
    logistic = entry.get("logisticModel")

    api_unit = line.get("salesUnit") if line else None
    unit, unit_source = (api_unit, "api") if api_unit else (None, None)
    if unit is None and catalog is not None:
        unit, unit_source = catalog.sales_unit, "catalog"
    if api_unit and catalog is not None and api_unit != catalog.sales_unit:
        flags.append("UNIT_MISMATCH")

    if line is None:
        qty_kind: QtyKind
        qty_kind, qty = "none", None
    else:
        qty_kind, qty = classify_amount(line.get("availableAmount"), logistic, api_unit, catalog)
    if qty_kind == "untracked":
        flags.append("STOCK_UNTRACKED")
    elif qty_kind == "terminal":
        flags.append("STOCK_UNKNOWN_TERMINAL")

    blocked = bool(entry.get("salesBlock")) or bool(line and line.get("salesBlock"))
    available = date.fromisoformat(line["availableDate"]) if line and line.get("availableDate") else None
    late_days = (available - need).days if available and need and available > need else None

    order_by = None
    estimated = False
    if entry.get("closingTime") and line is not None:
        order_by = to_helsinki(parse_api_time(entry["closingTime"]))
        if need and available and need > available and not blocked:
            # the snapshot repeats the Monday slot for later dates; keep the lead time (F-05)
            order_by = order_by + timedelta(days=(need - available).days)
            estimated = True
            flags.append("CUTOFF_ESTIMATED")
    approve_by = order_by - buffer if order_by else None
    cutoff_passed = bool(order_by and now >= order_by)
    too_close = bool(approve_by and not cutoff_passed and now >= approve_by)

    if not valid_id:
        feasibility: Feasibility = "unknown_id"
        flags.insert(0, "UNKNOWN_ID")
    elif line is None:
        feasibility = "not_deliverable"
    elif blocked:
        feasibility = "sales_blocked"
    elif qty_kind == "zero":
        feasibility = "out_of_stock"
    elif late_days:
        feasibility = "late"
    elif cutoff_passed:
        feasibility = "cutoff_passed"
    elif too_close:
        feasibility = "cutoff_too_close"
    elif qty_kind == "exact" and qty_needed is not None and qty is not None and Decimal(str(qty_needed)) > qty:
        feasibility = "partial"
    else:
        feasibility = "orderable"
    if valid_id and line is None:
        flags.append("NOT_DELIVERABLE")
        if availability is None:
            flags.append("NO_AVAILABILITY_DATA")  # nothing recorded or returned: not the API's empty answer
    if blocked:
        flags.append("SALES_BLOCKED")
    if qty_kind == "zero":
        flags.append("OUT_OF_STOCK")
    if late_days:
        flags.append("LATE")
    if cutoff_passed:
        flags.append("CUTOFF_PASSED")
    elif too_close:
        flags.append("CUTOFF_TOO_CLOSE")
    if qty_kind == "exact" and qty_needed is not None and qty is not None and Decimal(str(qty_needed)) > qty:
        flags.append("PARTIAL_STOCK")

    offer_price = _price(price) if price and valid_id else None
    delivery = need or available
    if offer_price is None:
        validity: Validity = "no_price"
        if valid_id:
            flags.append("NO_PRICE")
    elif delivery is None or offer_price.valid_from is None or offer_price.valid_to is None:
        validity = "unknown"
    elif offer_price.valid_from <= delivery <= offer_price.valid_to:
        validity = "valid"
    else:
        validity = "not_valid_for_delivery_date"
        flags.append("PRICE_NOT_VALID_FOR_DELIVERY_DATE")
    if offer_price is not None:
        if offer_price.net_price_found:
            flags.append("NET_PRICE")
        if offer_price.list_price is not None and offer_price.net > offer_price.list_price:
            flags.append("NET_ABOVE_LIST")
        if offer_price.discount_pct is not None and offer_price.discount_pct > DEEP_DISCOUNT_PCT:
            flags.append("DEEP_DISCOUNT")
        if offer_price.comparison_price is None:
            flags.append("NO_COMPARISON_PRICE")
    if catalog is not None:
        if catalog.deposits:
            flags.append("DEPOSIT_NOT_PRICED")
        if catalog.variable_unit:
            flags.append("CATCH_WEIGHT")

    return NormalisedOffer(
        product_id=pid,
        unit=unit,
        unit_source=unit_source,
        catalog_unit=catalog.sales_unit if catalog else None,
        qty_kind=qty_kind,
        qty=qty,
        logistic_model=logistic,
        available_date=available,
        need_date=need,
        late_days=late_days,
        order_by=order_by,
        order_by_estimated=estimated,
        approve_by=approve_by,
        cutoff_passed=cutoff_passed,
        blocked=blocked,
        feasibility=feasibility,
        price=offer_price,
        validity=validity,
        flags=list(dict.fromkeys(flags)),
        as_of=now,
        evidence=list(dict.fromkeys(evidence)),
    )


def normalise_offers(
    availability: ApiResult,
    price: ApiResult,
    *,
    as_of: datetime | Clock,
    need_date: date | str | None = None,
    catalogs: Mapping[str, CatalogUnits] | None = None,
    qty_needed: Mapping[str, Decimal | float | int] | None = None,
    buffer: timedelta = DEFAULT_BUFFER,
) -> list[NormalisedOffer]:
    """One offer per requested id (availability order, then price-only ids), plus one `unknown_id` offer per rejected
    id. `need_date` defaults to the requested date. Each offer cites the hashes of both raw responses."""
    catalogs = catalogs or {}
    qty_needed = qty_needed or {}
    need = need_date or availability.requested_date
    ids = list(dict.fromkeys([*availability.entries, *availability.missing, *price.entries, *price.missing]))
    offers = [
        normalise_offer(
            pid,
            availability.entry(pid),
            price.entry(pid),
            as_of=as_of,
            need_date=need,
            catalog=catalogs.get(pid),
            qty_needed=qty_needed.get(pid),
            buffer=buffer,
            evidence=[h for h in (availability.entry_evidence.get(pid), price.entry_evidence.get(pid)) if h],
        )
        for pid in ids
    ]
    seen = {r.raw for r in availability.rejected}
    rejected = [*availability.rejected, *(r for r in price.rejected if r.raw not in seen)]
    offers.extend(normalise_offer(r.raw, None, None, as_of=as_of, need_date=need, buffer=buffer) for r in rejected)
    return offers
