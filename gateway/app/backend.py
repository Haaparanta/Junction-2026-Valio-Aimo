"""Where product facts and prices come from: the stub catalogue, or the real catalogue with Valio Aimo answers.

Every route and service asks the app's one Backend (app.state.backend, picked once by create_app from the settings):

* StubBackend wraps app/stubs.py exactly: the small hand-made catalogue and its computed offers. CI and the test suite
  run on it, so nothing depends on the git-ignored data.
* CatalogBackend reads data/catalog.db (PLAN M2, scripts/build_catalog.py) with the M4 search, the M3.5 quantity
  planner and the M5 offers, priced by the M3 ValioClient: replayed from data/fixtures (scripts/record_fixtures.py)
  or live with VALIO_AIMO_API_KEY.

VALIO_MODE picks one (settings.valio_mode): auto (the default) is the catalogue with the recording when catalog.db and
fixtures/manifest.json both exist, else the stubs; stub, replay and live force one.

Both keep the offers they make (offer ids -> Offer, offer sets and the requests behind them), so create_quote, a
basket's "Add to basket" and the UI find them by id. Quotes, orders and approvals stay in StubState; they take their
product facts (ProductInfo), VAT rates, quote expiry and evidence, and the pre-order re-check (current) from here.

Thread safety: FastAPI runs sync routes on worker threads. CatalogBackend opens one read-only SQLite connection per
thread, and runs the async ValioClient on one event loop in its own thread, so the client's lock, cache and HTTP
connections only ever see that loop; a caller blocks on the result.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Coroutine, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from . import stubs
from .catalog import get_record, json_ld, open_catalog, summary_fields
from .clients.valio import ApiResult, ValioClient, ValioConfig, ValioError
from .contract import (
    ContentPerUnit,
    Evidence,
    Msg,
    NotOffered,
    Offer,
    OffersRequest,
    OffersResponse,
    PlanQuantityRequest,
    PlanQuantityResponse,
    ProductResponse,
    ProductSummary,
    QuoteLine,
    SearchRequest,
    SearchResponse,
    Substitute,
    SubstitutesRequest,
    SubstitutesResponse,
)
from .fmt import UNIT_EN, UNIT_FI, fi, helsinki_at, instant, num, quoted, to_helsinki
from .offers import OfferSet, Option, build_offer_set, build_product_offer, catalog_units, is_variant, product_offer
from .offers import shortlist as offers_shortlist
from .offers_model import normalise_offer
from .quantity import plan_quantity as plan_units
from .search import search as catalog_search

if TYPE_CHECKING:
    from .match import CatalogueEntry
    from .settings import Settings

T = TypeVar("T")
FOOD_VAT = stubs.FOOD_VAT  # only when the API never gave a product's rate (a quote is always priced first)
SUBSTITUTE_SET = "OS-SUBST"  # orders.py reads a quote line from this offer set as substituted
SUBSTITUTE_TAGS = ("drops_claim", "adds_allergen", "changes_unit", "price_jump")
MAX_SUBSTITUTES = 5
# Detailed normaliser flags that block delivering a quoted line, mapped to the contract's flags (M8.3 re-check).
BLOCKING_FLAGS = {
    "CUTOFF_PASSED": "CUTOFF_PASSED",
    "NOT_DELIVERABLE": "NOT_DELIVERABLE",
    "LATE": "NOT_DELIVERABLE",
    "SALES_BLOCKED": "NOT_DELIVERABLE",
    "UNKNOWN_ID": "NOT_DELIVERABLE",
    "OUT_OF_STOCK": "OUT_OF_STOCK",
    "PARTIAL_STOCK": "PARTIAL_STOCK",
}


class BackendUnavailable(Exception):
    """The settings ask for the catalogue but its files are missing."""


@dataclass(frozen=True)
class ProductInfo:
    """What quotes, orders, the policy and baskets need to know about one product."""

    product_id: str
    name_fi: str
    base_unit: str | None  # L, KG or PCS: what a need for it is measured in; None when the content is unknown
    sales_unit: str  # the catalogue's sales unit
    api_unit: str | None  # the API's unit (scheduleLines[].salesUnit) when known
    vat_rate: Decimal
    category: str
    temperature_class: str
    claims: tuple[str, ...]
    allergens: tuple[str, ...]  # GS1 codes it contains
    allergen_data: str  # declared | unknown
    variant: bool  # coffee milk, portion packs: offered only with the buyer's consent
    invented: bool  # a stub row with values not in the findings
    list_price: Decimal | None = None

    @property
    def unit_mismatch(self) -> bool:
        return self.api_unit is not None and self.api_unit != self.sales_unit


@dataclass(frozen=True)
class Current:
    """A quoted line read again just before ordering (M8.3)."""

    unit_price: Decimal | None  # None: no price any more
    blocking: tuple[str, ...]  # contract flags that block delivering the line's qty on its date
    order_by: datetime | None
    price_valid: bool = True  # False: the price does not hold on the delivery date


class Backend(Protocol):
    mode: str  # stub | replay | live
    registered_offers: dict[str, Offer]
    offer_sets: dict[str, OffersResponse]
    offer_requests: dict[str, OffersRequest]

    def search(self, req: SearchRequest) -> SearchResponse: ...

    def get_product(self, product_id: str) -> ProductResponse | None: ...

    def plan_quantity(self, req: PlanQuantityRequest) -> PlanQuantityResponse | None: ...

    def offers(self, req: OffersRequest, as_of: str) -> OffersResponse: ...

    def price_product(
        self, product_id: str, amount: float, unit: str, need_date: str, as_of: str
    ) -> tuple[Offer | None, NotOffered | None]: ...

    def substitutes(self, req: SubstitutesRequest, as_of: str) -> SubstitutesResponse: ...

    def product(self, product_id: str) -> ProductInfo | None: ...

    def units_for(self, req: OffersRequest) -> list[str]: ...

    def catalogue_entries(self) -> tuple[CatalogueEntry, ...]: ...

    def current(self, product_id: str, qty: int, delivery_date: str, now: datetime) -> Current | None: ...

    def quote_expiry(self, issued: datetime, lines: Iterable[tuple[str, str]]) -> datetime: ...

    def quote_evidence(self, lines: list[QuoteLine]) -> Evidence: ...

    def invented_warnings(self, ids: Iterable[str | None]) -> list[str]: ...

    def health(self) -> dict[str, Any]: ...


class OfferBook:
    """The offers a backend made, by id, so create_quote and the UI can use them (thread-safe)."""

    def __init__(self) -> None:
        self.book_lock = threading.Lock()
        self.registered_offers: dict[str, Offer] = {}
        self.offer_sets: dict[str, OffersResponse] = {}
        self.offer_requests: dict[str, OffersRequest] = {}

    def _register_set(self, req: OffersRequest, res: OffersResponse) -> None:
        with self.book_lock:
            self.registered_offers.update({o.offer_id: o for o in res.options})
            self.offer_sets[res.offer_set_id] = res
            self.offer_requests[res.offer_set_id] = req

    def _register(self, offer: Offer) -> None:
        with self.book_lock:
            self.registered_offers[offer.offer_id] = offer


# ---- the stub catalogue ----------------------------------------------------------------------------


class StubBackend(OfferBook):
    """app/stubs.py as it is. stubs.PRODUCTS is read on every call (tests swap rows in it)."""

    mode = "stub"

    def search(self, req: SearchRequest) -> SearchResponse:
        return stubs.search(req)

    def get_product(self, product_id: str) -> ProductResponse | None:
        return stubs.get_product(product_id)

    def plan_quantity(self, req: PlanQuantityRequest) -> PlanQuantityResponse | None:
        return stubs.plan_quantity(req)

    def offers(self, req: OffersRequest, as_of: str) -> OffersResponse:
        res = stubs.offers(req, as_of)
        self._register_set(req, res)
        return res

    def price_product(
        self, product_id: str, amount: float, unit: str, need_date: str, as_of: str
    ) -> tuple[Offer | None, NotOffered | None]:
        """(the offer, None) when the row delivers in full, else (None, why not); (None, None) when the product is
        not in the catalogue or is not priced per `unit`. The offer is registered under its offer_id."""
        p = stubs.PRODUCTS.get(product_id)
        if p is None or p.base_unit != unit:
            return None, None
        d, amt = date.fromisoformat(need_date), Decimal(str(amount))
        qty, ob, blocking = stubs.assess(p, amt, d, instant(as_of))
        if blocking or ob is None:
            return None, stubs.refusal(p, qty, d, ob, blocking)
        offer_set_id = "OP-" + stubs.sha(f"{p.id}|{num(amt)}|{unit}|{need_date}")[:8].upper()  # one product, one need
        o = stubs.make_offer(p, qty, d, ob, offer_set_id, "other")
        self._register(o)
        return o, None

    def substitutes(self, req: SubstitutesRequest, as_of: str) -> SubstitutesResponse:
        return stubs.substitutes(req)

    def product(self, product_id: str) -> ProductInfo | None:
        p = stubs.PRODUCTS.get(product_id)
        if p is None:
            return None
        return ProductInfo(
            product_id=p.id,
            name_fi=p.name,
            base_unit=p.base_unit,
            sales_unit=p.sales_unit,
            api_unit=p.api_unit,
            vat_rate=p.vat,
            category=p.category,
            temperature_class=p.temperature,
            claims=p.claims,
            allergens=p.allergens,
            allergen_data=p.allergen_data,
            variant=p.variant,
            invented=p.invented,
            list_price=getattr(p, "list_price", None),  # X-17: the stub rows carry none yet
        )

    def units_for(self, req: OffersRequest) -> list[str]:
        rows = [p for p in stubs.matches(req, stubs.heads_for(req)) if req.allow_variants or not p.variant]
        return sorted({p.base_unit for p in rows})

    def catalogue_entries(self) -> tuple[CatalogueEntry, ...]:
        from .match import catalogue_entries

        return catalogue_entries()

    def current(self, product_id: str, qty: int, delivery_date: str, now: datetime) -> Current | None:
        p = stubs.PRODUCTS.get(product_id)
        if p is None:
            return None
        d = date.fromisoformat(delivery_date)
        _, ob, blocking = stubs.assess(p, p.content * qty, d, now)
        return Current(unit_price=p.price, blocking=tuple(blocking), order_by=ob)

    def quote_expiry(self, issued: datetime, lines: Iterable[tuple[str, str]]) -> datetime:
        return stubs.quote_expiry(issued, lines)

    def quote_evidence(self, lines: list[QuoteLine]) -> Evidence:
        return stubs.stub_evidence(lines)

    def invented_warnings(self, ids: Iterable[str | None]) -> list[str]:
        return stubs.invented_warnings(ids)

    def health(self) -> dict[str, Any]:
        return {"mode": self.mode, "catalogue": "stub", "products": len(stubs.PRODUCTS)}


# ---- the real catalogue ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Terms:
    """What a priced (product, delivery date) carried: for quote expiry, evidence and VAT."""

    order_by: datetime | None
    valid_to: date | None
    tax_rate: Decimal | None
    evidence: tuple[str, ...]
    time_now: str | None


def _empty(endpoint: str, need_date: str) -> ApiResult:
    return ApiResult(
        endpoint=endpoint,  # type: ignore[arg-type]
        customer="",
        requested_date=need_date,
        entries={},
        entry_evidence={},
        evidence=[],
    )


def _content_per_unit(vote: Any, fallback_unit: str) -> ContentPerUnit:
    source = vote.source or ""
    if source == "vote":
        src = "vote"
    elif source == "api":
        src = "api_comparison_price"
    elif source == "name":
        src = "name"
    else:
        src = "units"
    return ContentPerUnit(
        value=num(vote.value) if vote.value is not None else "0",
        unit=vote.dim or fallback_unit,
        source=src,  # type: ignore[arg-type]
        confidence=vote.confidence or "low",
    )


def _summary(record: dict[str, Any]) -> ProductSummary:
    fields = summary_fields(record)
    fields["category"] = fields.get("category") or ""
    return ProductSummary(**fields)


class CatalogBackend(OfferBook):
    """catalog.db + search.py + quantity.py + offers.py, priced by the ValioClient (replay or live)."""

    def __init__(self, settings: Settings, mode: str, *, client: ValioClient | None = None) -> None:
        super().__init__()
        self.settings = settings  # as_of is read on every call: the demo clock may change
        self.mode = mode
        self.catalog_db = Path(settings.catalog_db)
        if not self.catalog_db.is_file():
            raise BackendUnavailable(f"no catalogue at {self.catalog_db}; run scripts/build_catalog.py")
        self.config = ValioConfig(
            mode="live" if mode == "live" else "replay",
            base_url=settings.valio_aimo_api_base_url.rstrip("/"),
            api_key=settings.valio_aimo_api_key,
            fixtures_dir=Path(settings.fixtures_dir),
        )
        if mode == "replay" and not (self.config.fixtures_dir / "manifest.json").is_file():
            raise BackendUnavailable(
                f"no fixture manifest in {self.config.fixtures_dir}; run scripts/record_fixtures.py"
            )
        if mode == "live" and not self.config.api_key:
            raise BackendUnavailable("VALIO_MODE=live needs VALIO_AIMO_API_KEY")
        self._client = client
        self._local = threading.local()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()
        self._terms: dict[tuple[str, str], Terms] = {}
        self._vat: dict[str, Decimal] = {}
        self._api_unit: dict[str, str] = {}
        self._list_price: dict[str, Decimal] = {}
        self._entries: tuple[CatalogueEntry, ...] | None = None
        self._entries_lock = threading.Lock()

    # -- plumbing ----------------------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """One read-only connection per thread (SQLite connections are thread-bound, tech-research §7)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = open_catalog(self.catalog_db)
            self._local.conn = conn
        return conn

    def _run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run a client coroutine on the backend's own event loop thread and wait for it."""
        with self._loop_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="valio-client", daemon=True).start()
                self._loop = loop
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _both(self, ids: list[str], need_date: str) -> tuple[ApiResult, ApiResult]:
        if self._client is None:  # created on the loop thread, the only one that ever uses it
            self._client = ValioClient(self.config)
        return await self._client.availability(ids, need_date), await self._client.price(ids, need_date)

    def _fetch(self, ids: Sequence[str], need_date: str) -> tuple[ApiResult, ApiResult]:
        ids = list(ids)
        if not ids:
            return _empty("availability", need_date), _empty("price", need_date)
        return self._run(self._both(ids, need_date))

    def close(self) -> None:
        if self._loop is not None:
            if self._client is not None:
                self._run(self._client.aclose())
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _default_date(self) -> str:
        """The first delivery day after the as-of clock: plan_quantity and VAT lookups have no date of their own."""
        return (to_helsinki(instant(self.settings.as_of)).date() + timedelta(days=1)).isoformat()

    def _remember(self, options: Iterable[Option], need_date: str, availability: ApiResult) -> None:
        for o in options:
            p = o.offer.price
            self._terms[(o.product_id, need_date)] = Terms(
                order_by=o.offer.order_by,
                valid_to=p.valid_to if p else None,
                tax_rate=p.tax_rate if p else None,
                evidence=tuple(o.offer.evidence),
                time_now=availability.time_now,
            )
            if p is not None and p.tax_rate is not None:
                self._vat[o.product_id] = p.tax_rate
            if p is not None and p.list_price is not None:
                self._list_price[o.product_id] = p.list_price
            if o.offer.unit_source == "api" and o.offer.unit:
                self._api_unit[o.product_id] = o.offer.unit

    # -- catalogue reads ---------------------------------------------------------------------------

    def search(self, req: SearchRequest) -> SearchResponse:
        res = catalog_search(
            self._conn(),
            req.query,
            req.heads,
            req.exclude,
            req.must_claims,
            req.must_not_allergens,
            req.temperature,
            req.limit,
        )
        n = res.total_matches
        if n == 0:
            msg = Msg(fi="En löytänyt sopivaa tuotetta.", en="I found no matching product.")
        elif n == 1:
            msg = Msg(fi="Löysin 1 sopivan tuotteen.", en="I found 1 matching product.")
        else:
            msg = Msg(fi=f"Löysin {n} sopivaa tuotetta.", en=f"I found {n} matching products.")
        return SearchResponse(
            products=[_summary(h.record) for h in res.hits],
            total_matches=n,
            message_for_user=msg,
            warnings=list(res.warnings),
        )

    def get_product(self, product_id: str) -> ProductResponse | None:
        record = get_record(self._conn(), product_id)
        if record is None:
            return None
        name = record.get("name_fi") or product_id
        return ProductResponse(
            product=_summary(record),
            json_ld=json_ld(record),
            message_for_user=Msg(fi=name, en=record.get("name_en") or name),
        )

    def product(self, product_id: str) -> ProductInfo | None:
        record = get_record(self._conn(), product_id)
        if record is None:
            return None
        if product_id not in self._vat:  # normally known from the offer the line was quoted from
            self._lookup_price(product_id)
        content = record.get("content") or {}
        return ProductInfo(
            product_id=product_id,
            name_fi=record.get("name_fi") or product_id,
            base_unit=content.get("dim") if content.get("value") is not None else None,
            sales_unit=record.get("sales_unit") or "",
            api_unit=self._api_unit.get(product_id),
            vat_rate=self._vat.get(product_id, FOOD_VAT),
            category=record.get("category") or "",
            temperature_class=record.get("temperature_class") or "unknown",
            claims=tuple(record.get("claims") or ()),
            allergens=tuple(record.get("allergens_contains") or ()),
            allergen_data=record.get("allergen_data") or "unknown",
            variant=is_variant(record, []),
            invented=False,
            list_price=self._list_price.get(product_id),
        )

    def _lookup_price(self, product_id: str) -> None:
        try:
            availability, price = self._fetch([product_id], self._default_date())
        except ValioError:
            return
        entry = price.entry(product_id) or {}
        rate = (entry.get("tax") or {}).get("taxRate")
        if rate is not None:
            self._vat[product_id] = Decimal(str(rate))
        lines = (availability.entry(product_id) or {}).get("scheduleLines") or []
        if lines and isinstance(lines[0], dict) and lines[0].get("salesUnit"):
            self._api_unit[product_id] = lines[0]["salesUnit"]

    def catalogue_entries(self) -> tuple[CatalogueEntry, ...]:
        """Every product as an import match entry (id, name, GTIN, variant), read once."""
        from .match import CatalogueEntry

        with self._entries_lock:
            if self._entries is None:
                rows = self._conn().execute(
                    "SELECT id, name_fi, name_en, sales_unit_gtin, consumer_gtin FROM products ORDER BY num"
                )
                self._entries = tuple(
                    CatalogueEntry(
                        product_id=r[0],
                        name=r[1] or r[2] or r[0],
                        gtin=r[3] or r[4] or None,
                        variant=is_variant({"name_fi": r[1] or ""}, []),
                    )
                    for r in rows
                )
            return self._entries

    def units_for(self, req: OffersRequest) -> list[str]:
        found = offers_shortlist(self._conn(), req)
        heads = list(found.interpretation.get("heads") or [])
        dims = set()
        for h in found.hits:
            dim = (h.record.get("content") or {}).get("dim")
            if dim and (req.allow_variants or not is_variant(h.record, heads, req.query)):
                dims.add(dim)
        return sorted(dims)

    # -- prices --------------------------------------------------------------------------------------

    def plan_quantity(self, req: PlanQuantityRequest) -> PlanQuantityResponse | None:
        record = get_record(self._conn(), req.product_id)
        if record is None:
            return None
        day = self._default_date()
        availability, price = self._fetch([req.product_id], day)
        name = record.get("name_fi") or req.product_id
        try:
            plan = plan_units(
                req.amount,
                req.unit,
                catalog=catalog_units(record),
                availability_entry=availability.entry(req.product_id),
                price_entry=price.entry(req.product_id),
            )
        except ValueError as e:
            return PlanQuantityResponse(
                product_id=req.product_id,
                api_unit=record.get("sales_unit") or "",
                content_per_unit=ContentPerUnit(value="0", unit=req.unit, source="units", confidence="low"),
                units_needed=0,
                total_content="0",
                overshoot="0",
                message_for_user=Msg(
                    fi=f"Tuotteelle {quoted(name)} ei voi laskea määrää.",
                    en=f"The quantity cannot be planned for {quoted(name)}.",
                ),
                warnings=[str(e)],
            )
        cpu = _content_per_unit(plan.content, req.unit)
        if plan.qty is None or plan.total_content is None:
            return PlanQuantityResponse(
                product_id=req.product_id,
                api_unit=plan.api_unit,
                content_per_unit=cpu,
                units_needed=0,
                total_content="0",
                overshoot="0",
                message_for_user=Msg(
                    fi=f"Tuotteen {quoted(name)} määrää ei voi laskea yksikössä {req.unit}.",
                    en=f"The quantity of {quoted(name)} cannot be planned in {req.unit}.",
                ),
                warnings=list(plan.warnings),
            )
        qty = int(plan.qty.to_integral_value(rounding=ROUND_CEILING))
        total = num(plan.total_content)
        return PlanQuantityResponse(
            product_id=req.product_id,
            api_unit=plan.api_unit,
            content_per_unit=cpu,
            units_needed=qty,
            total_content=total,
            overshoot=num(plan.overshoot or Decimal(0)),
            message_for_user=Msg(
                fi=f"{qty} × {plan.api_unit} = {fi(total)} {UNIT_FI[plan.need_unit]}.",
                en=f"{qty} × {plan.api_unit} = {total} {UNIT_EN[plan.need_unit]}.",
            ),
            warnings=list(plan.warnings),
        )

    def offers(self, req: OffersRequest, as_of: str) -> OffersResponse:
        """PLAN M5.1 (offers.get_offers), with the search and the ranking on the caller's thread."""
        conn = self._conn()
        found = offers_shortlist(conn, req)
        availability, price = self._fetch(found.ids, req.need_date)
        res: OfferSet = build_offer_set(req, found, availability, price, as_of=as_of, conn=conn)
        self._remember(res.options, req.need_date, availability)
        self._register_set(req, res.response)
        return res.response

    def price_product(
        self, product_id: str, amount: float, unit: str, need_date: str, as_of: str
    ) -> tuple[Offer | None, NotOffered | None]:
        conn = self._conn()
        record = get_record(conn, product_id)
        if record is None:
            return None, None
        availability, price = self._fetch([product_id], need_date)
        res = build_product_offer(
            product_id, record, amount, unit, need_date, availability, price, as_of=as_of, conn=conn
        )
        self._remember(res.options, need_date, availability)
        offer, why = product_offer(res)
        if offer is not None:
            self._register(offer)
        return offer, why

    def substitutes(self, req: SubstitutesRequest, as_of: str) -> SubstitutesResponse:
        """The catalogue's substitution candidates (M2.5), each priced for the need; every one needs approval."""
        record = get_record(self._conn(), req.product_id)
        subs: list[Substitute] = []
        for edge in (record or {}).get("substitutes") or []:
            if len(subs) == MAX_SUBSTITUTES:
                break
            info = self.product(edge["product_id"])
            if info is None:
                continue
            offer, _ = self.price_product(info.product_id, req.amount, req.unit, req.need_date, as_of)
            if offer is not None:
                offer = offer.model_copy(update={"offer_id": f"{SUBSTITUTE_SET}:{info.product_id}", "tier": "other"})
                self._register(offer)
            tags = [t for t in SUBSTITUTE_TAGS if t in (edge.get("risk") or [])]
            subs.append(
                Substitute(
                    product_id=info.product_id,
                    name_fi=info.name_fi,
                    risk_tags=[*tags, "needs_approval"],  # type: ignore[list-item]
                    offer=offer,
                )
            )
        n = sum(1 for s in subs if s.offer is not None)
        if n:
            msg = Msg(
                fi=f"Löysin {n} korvaavaa tuotetta, jotka voidaan toimittaa; korvaaminen vaatii hyväksynnän.",
                en=f"I found {n} substitute{'' if n == 1 else 's'} that can be delivered; any substitution needs "
                "approval.",
            )
        else:
            msg = Msg(
                fi="En löytänyt korvaavaa tuotetta, joka voidaan toimittaa.",
                en="I found no substitute that can be delivered.",
            )
        return SubstitutesResponse(original_product_id=req.product_id, substitutes=subs, message_for_user=msg)

    def current(self, product_id: str, qty: int, delivery_date: str, now: datetime) -> Current | None:
        record = get_record(self._conn(), product_id)
        if record is None:
            return None
        availability, price = self._fetch([product_id], delivery_date)
        evidence = [h for h in (availability.entry_evidence.get(product_id), price.entry_evidence.get(product_id)) if h]
        offer = normalise_offer(
            product_id,
            availability.entry(product_id),
            price.entry(product_id),
            as_of=now,
            need_date=delivery_date,
            catalog=catalog_units(record),
            qty_needed=qty,
            evidence=evidence,
        )
        blocking = tuple(dict.fromkeys(BLOCKING_FLAGS[f] for f in offer.flags if f in BLOCKING_FLAGS))
        return Current(
            unit_price=offer.price.net if offer.price else None,
            blocking=blocking,
            order_by=offer.order_by,
            price_valid=offer.validity != "not_valid_for_delivery_date",
        )

    # -- quotes --------------------------------------------------------------------------------------

    def quote_expiry(self, issued: datetime, lines: Iterable[tuple[str, str]]) -> datetime:
        """min(issue + TTL, each line's cut-off, the end of each price's validTo day) (M6.4, F-07)."""
        times = [issued + stubs.QUOTE_TTL]
        for product_id, delivery in lines:
            t = self._terms.get((product_id, delivery))
            if t is None:
                continue
            if t.order_by is not None:
                times.append(t.order_by)
            if t.valid_to is not None and t.valid_to < date.max:
                times.append(helsinki_at(t.valid_to + timedelta(days=1), "00:00"))
        return min(times)

    def quote_evidence(self, lines: list[QuoteLine]) -> Evidence:
        """The API's timeNow and the SHA-256 of every raw response the quote's lines were priced from (M6.2)."""
        hashes: list[str] = []
        times: list[str] = []
        for x in lines:
            t = self._terms.get((x.product_id, x.delivery_date))
            if t is None:
                continue
            hashes += [h for h in t.evidence if h not in hashes]
            if t.time_now:
                times.append(t.time_now)
        return Evidence(api_time_now=max(times) if times else None, response_sha256=hashes, stub=False)

    def invented_warnings(self, ids: Iterable[str | None]) -> list[str]:
        return []

    def health(self) -> dict[str, Any]:
        conn = self._conn()
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        out: dict[str, Any] = {
            "mode": self.mode,
            "catalogue": "catalog.db",
            "products": conn.execute("SELECT count(*) FROM products").fetchone()[0],
            "catalogue_built_at": meta.get("built_at"),
        }
        if self.mode == "replay":
            try:
                manifest = json.loads((self.config.fixtures_dir / "manifest.json").read_text())
                out["fixtures_recorded_at"] = manifest.get("recorded_started_at")
            except (OSError, ValueError):
                out["fixtures_recorded_at"] = None
        return out


# ---- picking one -----------------------------------------------------------------------------------


def resolve_mode(settings: Settings) -> str:
    """stub, replay or live for these settings. auto: replay when catalog.db and fixtures/manifest.json exist."""
    mode = settings.valio_mode
    if mode != "auto":
        return mode
    if Path(settings.catalog_db).is_file() and (Path(settings.fixtures_dir) / "manifest.json").is_file():
        return "replay"
    return "stub"


def create_backend(settings: Settings) -> Backend:
    mode = resolve_mode(settings)
    if mode == "stub":
        return StubBackend()
    return CatalogBackend(settings, mode)
