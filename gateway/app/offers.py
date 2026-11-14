"""Offer comparison and good-better-best (PLAN M5; findings R-01..R-07, W-03..W-05).

One need (what, how much, by when, preferences) becomes ranked, explained options:

1. **Shortlist** with the M4 search (heads, exclusions, claims and allergens applied in code). Compound variants the
   search drops by default but a buyer may accept ('kahvimaito' for 'maito') are searched too, so they can be shown
   as variants; they are offered only with `allow_variants`.
2. **Plan the quantity** for each shortlisted product (M3.5: content vote, lot rounding), in whole order units.
3. **Price and availability** for the shortlisted ids only, through the M3 client (replay or live).
4. **Hard gates** (R-01), never traded off: diet (re-checked here on the record), deliverable by the date, cut-off
   still open with the approval buffer, not blocked, in stock, priced, price valid on the delivery date, and a
   content that converts to the need's unit. Anything that fails goes to `not_offered` with the reason.
5. **Signals** scaled 0..1 (R-02): price per L or kg, cut-off slack (delivery), stock confidence (availability),
   delivery reliability (an unknown value is estimated: the category mean shrunk towards the global mean 0.972 and
   capped at 0.97, labelled "estimated"), soft preferences, and carbon (a category average). Weighted by the buyer's
   preference profile (R-04); OTIF = delivery x availability x reliability gives the band A/B/C (R-03).
6. **Rank** by band, score, OTIF, total, known reliability, carbon, Stock before Terminal, fewer units, id (R-04),
   so the order is deterministic. **Good-better-best** (R-05): BEST is rank 1; BETTER and GOOD are the next offers
   that are a real alternative to every pick so far. When rank 1 is exact stock that does not cover the need, or
   nothing covers it, a **split plan** fills the need greedily down the ranking (W-04, X-10).
7. **Explanations** (R-06, W-05) in Finnish and English with the live numbers. Totals use the quote's VAT rule
   (F-06: VAT per line, rounded half-up), so the numbers read out are the numbers quoted.

`get_offers(req, conn=..., client=..., as_of=...)` runs all of it and returns an `OfferSet`: `.response` is the
contract's `OffersResponse` (the shape stubs.offers() returns), and `.as_dict()` adds the structured ranking (scores,
weighted contributions, OTIF, band, detailed flags, split plan) for other agents. `build_offer_set` is the same
without I/O, over search and API results the caller already has.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Literal, Protocol, get_args

from .catalog import allergen_status, get_record, has_claim
from .clients.valio import ApiResult
from .contract import Msg, NotOffered, Offer, OfferFlag, OffersRequest, OffersResponse
from .fmt import at_en, at_fi, day_en, day_fi, quoted
from .offers_model import DEFAULT_BUFFER, Clock, NormalisedOffer, normalise_offer, parse_api_time, to_helsinki
from .quantity import CatalogUnits, QuantityPlan, StaticContent, plan_quantity
from .search import (
    DEFAULT_MODIFIERS,
    MAX_LIMIT,
    VARIANT_MODIFIERS,
    HeadMatch,
    Hit,
    SearchResult,
    _variant,
    _variant_words,
    fold,
    match_head,
    parse_heads,
    read_query,
    search,
)

# ---- weights and constants (R-02..R-05) -----------------------------------------------------

SIGNALS = ("price", "delivery", "availability", "reliability", "preference", "carbon")


@dataclass(frozen=True)
class Weights:
    price: float
    delivery: float
    availability: float
    reliability: float
    preference: float
    carbon: float

    def as_dict(self) -> dict[str, float]:
        return {s: getattr(self, s) for s in SIGNALS}


PROFILES: dict[str, Weights] = {  # R-04
    "balanced": Weights(0.35, 0.20, 0.15, 0.15, 0.10, 0.05),
    "cost_saver": Weights(0.55, 0.15, 0.10, 0.10, 0.05, 0.05),
    "safe_delivery": Weights(0.20, 0.30, 0.25, 0.20, 0.05, 0.0),
    "green": Weights(0.25, 0.15, 0.10, 0.10, 0.15, 0.25),
}
PREFERENCE_PROFILE = {  # the contract's preference -> R-04 profile
    "cheapest": "cost_saver",
    "greenest": "green",
    "most_reliable": "safe_delivery",
    "balanced": "balanced",
}

GLOBAL_RELIABILITY = 0.972  # D-10 mean over the 4,425 products with a value
RELIABILITY_CAP = 0.97  # an estimate never claims more than this (R-02)
RELIABILITY_PRIOR = 20  # pseudo-deliveries of the global mean when shrinking a category mean
SLACK_HOURS = 6  # cut-off at least this far away scores 1.0, closer 0.8 (R-02)
ESTIMATED_CUTOFF_FACTOR = 0.9  # an estimated cut-off (F-05) is less certain than the API's own
BAND_A, BAND_B = 0.85, 0.60  # R-03
ALT_CONTENT = Decimal("0.10")  # R-05: pack content differing by more than 10 % is a real alternative
ALT_PRICE = Decimal("0.05")  # or unit price differing by more than 5 %
CENT = Decimal("0.01")
# Words that make a product a variant the buyer has to accept (W-01: Cafè milk, barista versions; condensed or
# sweetened milk is not drinking milk either). Folded word starts.
CONSENT_WORDS = ("cafe", "barista", "kondensoi", "makeutet", "condensed", "sweetened")

Gate = Literal[
    "unknown_id",
    "not_deliverable",
    "sales_blocked",
    "out_of_stock",
    "late",
    "cutoff_passed",
    "cutoff_too_close",
    "no_price",
    "price_not_valid",
    "not_comparable",
    "variant",
    "partial",
]
CONTRACT_FLAGS: tuple[str, ...] = get_args(OfferFlag)
# Detailed flags without a contract counterpart map onto the nearest one; the reason text says which it was.
FLAG_MAP = {"CUTOFF_TOO_CLOSE": "CUTOFF_PASSED", "LATE": "NOT_DELIVERABLE", "UNKNOWN_ID": "NOT_DELIVERABLE"}
COUNT_KEYS = (
    "candidates",
    "on_time_full",
    "offered",
    "partial",
    "split_lines",
    "cutoff_passed",
    "cutoff_too_close",
    "cutoff_passed_terminal",
    "not_deliverable",
    "out_of_stock",
    "sales_blocked",
    "late",
    "no_price",
    "price_not_valid",
    "not_comparable",
    "variant_withheld",
    "stock_full",
    "terminal_full",
)
GATE_COUNT = {"unknown_id": "not_deliverable", "variant": "variant_withheld"}

TIER_LABEL = {"best": ("PARAS", "BEST"), "better": ("PAREMPI", "BETTER"), "good": ("HYVÄ", "GOOD")}
TAG_TEXT = {
    "lowest price": ("edullisin", "lowest price"),
    "safest delivery": ("varmin toimitus", "safest delivery"),
    "lowest carbon": ("pienin hiilijalanjälki", "lowest carbon"),
    "meets all must-haves": ("täyttää kaikki vaatimukset", "meets all must-haves"),
}
UNIT_WORD = {"L": ("l", "L"), "KG": ("kg", "kg"), "PCS": ("kpl", "pcs")}


# ---- formatting -----------------------------------------------------------------------------


def _q(value: Decimal | float | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(d: Decimal) -> str:
    """The contract's money string: two places, half-up (F-06)."""
    return str(d.quantize(CENT, rounding=ROUND_HALF_UP))


def _norm(d: Decimal) -> Decimal:
    q = d.normalize()
    return q.quantize(Decimal(1)) if q == q.to_integral_value() else q


def en_money(d: Decimal) -> str:
    return f"{d.quantize(CENT, rounding=ROUND_HALF_UP):,}"  # 1,010.00


def fi_money(d: Decimal) -> str:
    return en_money(d).replace(",", " ").replace(".", ",")  # 1 010,00


def en_num(d: Decimal | float | int) -> str:
    return f"{_norm(_q(d)):,f}"  # 1,000 · 20.3 · 3.75


def fi_num(d: Decimal | float | int) -> str:
    return en_num(d).replace(",", " ").replace(".", ",")


def fi_dec(d: Decimal) -> str:
    """A fixed-point number as written, with a decimal comma: 31.0 -> '31,0' (no trailing zeros dropped)."""
    return str(d).replace(".", ",")


_FI_DATE_STOP = re.compile(r"(\b\d{1,2}\.\d{1,2}\.)\.")


def fi_text(text: str) -> str:
    """A Finnish date such as 'ma 16.11.' already ends a sentence: 'ma 16.11..' becomes 'ma 16.11.'."""
    return _FI_DATE_STOP.sub(r"\1", text)


def _en_date(d: date) -> str:
    return f"{d.day}.{d.month}.{d.year}"


def _hours(delta: timedelta) -> Decimal:
    return (Decimal(delta.total_seconds()) / 3600).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _rel_diff(a: Decimal, b: Decimal) -> Decimal:
    top = max(abs(a), abs(b))
    return Decimal(0) if top == 0 else abs(a - b) / top


# ---- inputs from the catalogue --------------------------------------------------------------


def catalog_units(record: Mapping[str, Any]) -> CatalogUnits:
    """The planner's catalogue facts from an M2 compact record, with its static and name content as vote inputs."""
    units = {
        u["unit"]: _q(u["size_in_base"])
        for u in record.get("units") or []
        if isinstance(u, Mapping) and u.get("unit") and u.get("size_in_base")
    }
    content = record.get("content") or {}
    statics: list[StaticContent] = []
    for key, confidence in (("static", "medium"), ("name", "low")):
        v = content.get(key) or {}
        if v.get("per_base") and v["per_base"] > 0 and v.get("dim") in ("L", "KG", "PCS"):
            statics.append(
                StaticContent(
                    value=_q(v["per_base"]),
                    dim=v["dim"],
                    per_unit=record.get("base_unit") or record["sales_unit"],
                    source=v.get("source") or key,
                    confidence=confidence,
                )
            )
    return CatalogUnits(
        product_id=record["product_id"],
        sales_unit=record["sales_unit"],
        base_unit=record.get("base_unit") or record["sales_unit"],
        units=units,
        allowed_lot_size=_q(record.get("allowed_lot_size") or "0.01"),
        variable_unit=bool(record.get("variable_unit")),
        deposits=list(record.get("deposits") or []),
        static_content=statics,
    )


def estimate_reliability(n_known: int, mean_known: float | None) -> float:
    """R-02: an unknown reliability is the category mean shrunk towards the global mean, capped at 0.97.

    Imputing the category median would give exactly 1.0 to 63.6 % of products without data (D-10), so a product
    with no history never looks as safe as one with a perfect record."""
    if n_known <= 0 or mean_known is None:
        base = GLOBAL_RELIABILITY
    else:
        base = (n_known * mean_known + RELIABILITY_PRIOR * GLOBAL_RELIABILITY) / (n_known + RELIABILITY_PRIOR)
    return round(min(RELIABILITY_CAP, base), 3)


def _category_reliability(conn: sqlite3.Connection | None, category: str, cache: dict[str, float]) -> float:
    if category in cache:
        return cache[category]
    n, mean = 0, None
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT COUNT(reliability), AVG(reliability) FROM products"
                " WHERE category = ? AND reliability IS NOT NULL",
                (category,),
            ).fetchone()
            n, mean = int(row[0] or 0), row[1]
        except sqlite3.Error:
            pass
    cache[category] = estimate_reliability(n, mean)
    return cache[category]


def consent_heads(heads: Iterable[str]) -> list[str]:
    """Compound heads the search drops by default that are variants a buyer may accept: a modifier listed both in
    DEFAULT_MODIFIERS and VARIANT_MODIFIERS ('kahvi' + 'maito' = 'kahvimaito')."""
    out: list[str] = []
    for h in heads:
        hf = fold(h)
        for key, mods in DEFAULT_MODIFIERS.items():
            if hf.startswith(fold(key)):
                out += [m + h for m in mods if m in VARIANT_MODIFIERS and fold(m) not in hf]
    return [h for h in dict.fromkeys(out) if h not in heads]


def is_variant(record: Mapping[str, Any], heads: Sequence[str], query: str = "") -> bool:
    """A variant needs the buyer's consent (W-01): coffee or café milk, portion packs, flavoured or processed forms."""
    name = record.get("name_fi") or ""
    words = [fold(w) for w in name.split()]
    if any(w.startswith(c) for w in words for c in CONSENT_WORDS):
        return True
    parsed = parse_heads(heads)
    if not parsed:
        return False
    m = match_head(name, parsed)
    if not isinstance(m, HeadMatch):
        return m is not None  # found only through a consent head: the plain heads rule it out
    asked = [*read_query(query).content, *(w for h in parsed for w in (h.word, *h.before))]
    return _variant(m, name, _variant_words(asked)) > 0


# ---- one candidate --------------------------------------------------------------------------


@dataclass
class Option:
    """One shortlisted product for one need: its offer, plan, gate, signals and place in the ranking."""

    product_id: str
    record: dict[str, Any]
    offer: NormalisedOffer
    plan: QuantityPlan | None
    variant: bool
    qty: Decimal | None = None  # whole API units that cover the need (or, in a split, this line's share)
    content: Decimal | None = None  # need units per API unit
    max_qty: Decimal | None = None  # whole API units an exact stock amount allows
    gate: Gate | None = None  # why it is not offered as a full option; None or "partial" means ranked
    base_gate: Gate | None = None  # the gate before the variant rule: None means it covers the need on time
    flags: list[str] = field(default_factory=list)  # detailed: normaliser + plan + VARIANT + WHOLE_UNITS
    signals: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    otif: float = 0.0
    band: Literal["A", "B", "C"] = "C"
    reliability: float | None = None
    reliability_estimated: bool = False
    carbon: float | None = None
    rank: int | None = None
    tier: Literal["best", "better", "good", "other"] = "other"
    tags: list[str] = field(default_factory=list)
    split_line: int | None = None  # 1-based line number in the split plan

    # -- numbers ------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self.record.get("name_fi") or self.product_id

    @property
    def vendor(self) -> str:
        return self.record.get("vendor") or ""

    @property
    def unit(self) -> str:
        return (self.plan.api_unit if self.plan else None) or self.offer.unit or self.record.get("sales_unit", "")

    @property
    def unit_price(self) -> Decimal | None:
        return self.offer.price.net if self.offer.price else None

    @property
    def total_net(self) -> Decimal | None:
        if self.qty is None or self.unit_price is None:
            return None
        return (self.qty * self.unit_price).quantize(CENT, rounding=ROUND_HALF_UP)

    @property
    def vat(self) -> Decimal | None:
        """F-06: VAT on the line's net total, rounded half-up, as the quote computes it."""
        rate = self.offer.price.tax_rate if self.offer.price else None
        if self.total_net is None or rate is None:
            return None
        return (self.total_net * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)

    @property
    def total_gross(self) -> Decimal | None:
        return None if self.vat is None or self.total_net is None else self.total_net + self.vat

    @property
    def total_content(self) -> Decimal | None:
        return None if self.qty is None or self.content is None else _norm(self.qty * self.content)

    @property
    def price_per_content(self) -> Decimal | None:
        if self.unit_price is None or not self.content:
            return None
        return self.unit_price / self.content

    @property
    def stock(self) -> Literal["untracked", "known", "unknown_terminal", "none"]:
        return {"untracked": "untracked", "exact": "known", "terminal": "unknown_terminal"}.get(
            self.offer.qty_kind, "none"
        )  # type: ignore[return-value]

    @property
    def full(self) -> bool:
        return self.gate is None

    def contract_flags(self) -> list[OfferFlag]:
        mapped = {FLAG_MAP.get(f, f) for f in self.flags}
        if self.gate == "partial":
            mapped.add("PARTIAL_STOCK")
        return [f for f in CONTRACT_FLAGS if f in mapped]  # type: ignore[misc]

    def as_dict(self) -> dict[str, Any]:
        """R-06 structured form: everything an agent needs to check the ranking."""
        return {
            "product_id": self.product_id,
            "name_fi": self.name,
            "vendor": self.vendor,
            "rank": self.rank,
            "tier": self.tier,
            "tags": self.tags,
            "gate": self.gate,
            "split_line": self.split_line,
            "variant": self.variant,
            "api_unit": self.unit,
            "qty": None if self.qty is None else str(_norm(self.qty)),
            "content_per_unit": None if self.content is None else str(_norm(self.content)),
            "content_total": None if self.total_content is None else str(self.total_content),
            "unit_price_net": None if self.unit_price is None else money(self.unit_price),
            "total_net": None if self.total_net is None else money(self.total_net),
            "total_gross": None if self.total_gross is None else money(self.total_gross),
            "price_per_content": None if self.price_per_content is None else money(self.price_per_content),
            "logistic_model": self.offer.logistic_model,
            "stock": self.stock,
            "stock_qty": None if self.offer.qty is None else str(_norm(self.offer.qty)),
            "order_by": self.offer.order_by.isoformat() if self.offer.order_by else None,
            "order_by_estimated": self.offer.order_by_estimated,
            "approve_by": self.offer.approve_by.isoformat() if self.offer.approve_by else None,
            "feasibility": self.offer.feasibility,
            "signals": {k: round(v, 4) for k, v in self.signals.items()},
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "score": round(self.score, 4),
            "otif": round(self.otif, 4),
            "band": self.band,
            "reliability": self.reliability,
            "reliability_source": "estimated" if self.reliability_estimated else "product_history",
            "carbon_kg_co2e_per_kg": self.carbon,
            "flags": self.flags,
            "contract_flags": self.contract_flags(),
            "plan_warnings": list(self.plan.warnings) if self.plan else [],
            "evidence": list(self.offer.evidence),
        }


@dataclass
class SplitPlan:
    """W-04: lines filled greedily down the ranking. Exact stock lines are firm, others unconfirmed."""

    lines: list[Option]
    need: Decimal
    unit: str
    covered: Decimal
    shortfall: Decimal
    total_net: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "lines": [
                {
                    "product_id": o.product_id,
                    "qty": str(_norm(o.qty or Decimal(0))),
                    "api_unit": o.unit,
                    "content": str(o.total_content),
                    "total_net": money(o.total_net or Decimal(0)),
                    "firm": o.offer.qty_kind == "exact",
                }
                for o in self.lines
            ],
            "need": str(_norm(self.need)),
            "unit": self.unit,
            "covered": str(_norm(self.covered)),
            "shortfall": str(_norm(self.shortfall)),
            "total_net": money(self.total_net),
        }


@dataclass
class OfferSet:
    response: OffersResponse
    options: list[Option]  # every shortlisted product, ranked ones first in rank order
    split: SplitPlan | None
    profile: str
    weights: Weights
    interpretation: dict[str, Any]
    evidence: list[str]

    @property
    def ranked(self) -> list[Option]:
        return [o for o in self.options if o.rank is not None]

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.response.model_dump(),
            "profile": self.profile,
            "weights": self.weights.as_dict(),
            "ranking": [o.as_dict() for o in self.options],
            "split": self.split.as_dict() if self.split else None,
            "search": self.interpretation,
            "evidence": self.evidence,
        }


# ---- quantities -----------------------------------------------------------------------------


def _whole_up(qty: Decimal, step: Decimal | None) -> Decimal:
    """The smallest multiple of the lot step at or above qty that is a whole number (the contract counts units)."""
    if qty == qty.to_integral_value():
        return _norm(qty)
    if step and step > 0:
        k = (qty / step).to_integral_value(rounding=ROUND_CEILING)
        for _ in range(1000):
            v = k * step
            if v == v.to_integral_value():
                return _norm(v)
            k += 1
    return qty.to_integral_value(rounding=ROUND_CEILING)


def _whole_down(qty: Decimal, step: Decimal | None) -> Decimal:
    if qty <= 0:
        return Decimal(0)
    if qty == qty.to_integral_value():
        return _norm(qty)
    if step and step > 0:
        k = (qty / step).to_integral_value(rounding=ROUND_FLOOR)
        while k > 0:
            v = k * step
            if v == v.to_integral_value():
                return _norm(v)
            k -= 1
        return Decimal(0)
    return qty.to_integral_value(rounding=ROUND_FLOOR)


def _content_of(plan: QuantityPlan) -> Decimal | None:
    if plan.qty is None or plan.total_content is None or plan.qty == 0:
        return None
    return plan.total_content / plan.qty


# ---- the pipeline ---------------------------------------------------------------------------


def _diet_ok(record: Mapping[str, Any], claims: Sequence[str], banned: Sequence[str]) -> bool:
    """R-01 gate 1, re-checked on the record: every claim explicit, no banned allergen contained or unknown."""
    for c in claims:
        if has_claim(record, c) is not True:
            return False
    return all(allergen_status(record, a) not in ("unknown", "contains") for a in banned)


def _assess(
    pid: str,
    record: dict[str, Any],
    need: Decimal,
    need_unit: str,
    need_date: date,
    availability: ApiResult,
    price: ApiResult,
    now: datetime,
    buffer: timedelta,
    variant: bool,
) -> Option:
    catalog = catalog_units(record)
    a_entry, p_entry = availability.entry(pid), price.entry(pid)
    evidence = [h for h in (availability.entry_evidence.get(pid), price.entry_evidence.get(pid)) if h]
    kw: dict[str, Any] = {"as_of": now, "need_date": need_date, "catalog": catalog, "buffer": buffer}
    offer = normalise_offer(pid, a_entry, p_entry, evidence=evidence, **kw)
    plan: QuantityPlan | None
    try:
        plan = plan_quantity(
            need,
            need_unit,
            catalog=catalog,
            api_unit=offer.unit if offer.unit_source == "api" else None,
            price_entry=p_entry,
            stock_kind=offer.qty_kind,
            stock_qty=offer.qty,
        )
    except ValueError:
        plan = None
    opt = Option(product_id=pid, record=record, offer=offer, plan=plan, variant=variant)
    if plan is not None and plan.qty is not None:
        opt.content = _content_of(plan)
        opt.qty = _whole_up(plan.qty, plan.step)
        if opt.qty != plan.qty:
            opt.flags.append("WHOLE_UNITS")
        if offer.qty_kind == "exact" and offer.qty is not None:
            opt.max_qty = _whole_down(plan.max_orderable if plan.max_orderable is not None else offer.qty, plan.step)
        elif offer.qty_kind == "zero":
            opt.max_qty = Decimal(0)
        offer = normalise_offer(pid, a_entry, p_entry, evidence=evidence, qty_needed=opt.qty, **kw)
        opt.offer = offer
    opt.flags = list(dict.fromkeys([*offer.flags, *(plan.flags if plan else []), *opt.flags]))
    if variant:
        opt.flags.append("VARIANT")

    feas = offer.feasibility
    if feas not in ("orderable", "partial"):
        opt.gate = feas
    elif offer.price is None:
        opt.gate = "no_price"
    elif offer.validity == "not_valid_for_delivery_date":
        opt.gate = "price_not_valid"
    elif opt.qty is None or opt.content is None or opt.qty <= 0:
        opt.gate = "not_comparable"
    elif feas == "partial" or (opt.max_qty is not None and opt.max_qty < opt.qty):
        opt.gate = "partial"
    opt.base_gate = opt.gate
    return opt


def _signals(opts: list[Option], now: datetime, weights: Weights) -> None:
    """R-02 signals, R-03 OTIF and band, R-04 score, for the options that can be ranked."""
    ppcs = [o.price_per_content for o in opts if o.price_per_content is not None and o.price_per_content > 0]
    min_ppc = min(ppcs) if ppcs else None
    carbons = [o.carbon for o in opts if o.carbon is not None]
    min_carbon = min(carbons) if carbons else None
    for o in opts:
        s: dict[str, float] = {}
        ppc = o.price_per_content
        s["price"] = float(min_ppc / ppc) if min_ppc is not None and ppc else 0.0
        off = o.offer
        if off.cutoff_passed:
            delivery = 0.15
        elif off.late_days:
            delivery = 0.5**off.late_days
        elif off.order_by is None:
            delivery = 0.5
        else:
            delivery = 1.0 if (off.order_by - now) >= timedelta(hours=SLACK_HOURS) else 0.8
            if off.order_by_estimated:
                delivery *= ESTIMATED_CUTOFF_FACTOR
        s["delivery"] = delivery
        if off.qty_kind == "exact":
            if o.gate == "partial" and o.qty and o.max_qty is not None and o.content is not None:
                coverage = min(Decimal(1), (o.max_qty * o.content) / (o.qty * o.content))
                s["availability"] = 0.9 * float(coverage)
            else:
                s["availability"] = 1.0
        elif off.qty_kind == "untracked":
            s["availability"] = 0.95
        elif off.qty_kind == "terminal":
            s["availability"] = 0.75
        else:
            s["availability"] = 0.0
        s["reliability"] = float(o.reliability or 0.0)
        s["preference"] = 1.0  # no soft preferences in the request: equal for all, so it never re-orders
        if min_carbon is None:
            s["carbon"] = 1.0
        elif o.carbon is None:
            s["carbon"] = 0.5
        else:
            s["carbon"] = 1.0 if o.carbon <= 0 else float(min_carbon / o.carbon)
        o.signals = s
        w = weights.as_dict()
        o.contributions = {k: w[k] * s[k] for k in SIGNALS}
        o.score = sum(o.contributions.values())
        o.otif = s["delivery"] * s["availability"] * s["reliability"]
        o.band = "A" if o.otif >= BAND_A else "B" if o.otif >= BAND_B else "C"


def _rank_key(o: Option) -> tuple:
    return (
        o.band,
        -round(o.score, 9),
        -round(o.otif, 9),
        o.total_net if o.total_net is not None else Decimal("Infinity"),
        o.reliability_estimated,
        o.carbon if o.carbon is not None else float("inf"),
        o.offer.logistic_model != "Stock",
        o.qty or Decimal(0),
        o.product_id,
    )


def _real_alternative(o: Option, picks: Sequence[Option]) -> bool:
    """R-05: another vendor, another logistic model, pack content > 10 % apart, or unit price > 5 % apart."""

    def differs(p: Option) -> bool:
        if o.vendor != p.vendor or o.offer.logistic_model != p.offer.logistic_model:
            return True
        if o.content and p.content and _rel_diff(o.content, p.content) > ALT_CONTENT:
            return True
        a, b = o.price_per_content, p.price_per_content
        return bool(a and b and _rel_diff(a, b) > ALT_PRICE)

    return all(differs(p) for p in picks)


def _tags(full: list[Option], picks: list[Option], must_haves: bool) -> None:
    """R-05 role tags. A tag goes to a pick whose value is the best of all full options and is not shared with
    another pick, so 'lowest carbon' only appears when the values differ."""

    def tag(name: str, value: Callable[[Option], Any]) -> None:
        values = [value(o) for o in full if value(o) is not None]
        if len(set(values)) < 2:  # a tag says how a pick differs; one value says nothing
            return
        top = min(values)
        winners = [o for o in picks if value(o) == top]
        if len(winners) == 1:
            winners[0].tags.append(name)

    tag("lowest price", lambda o: o.price_per_content)
    tag("safest delivery", lambda o: -round(o.otif, 6))
    tag("lowest carbon", lambda o: o.carbon)
    if must_haves and picks:
        picks[0].tags.append("meets all must-haves")


def _split(ranked: list[Option], need: Decimal, unit: str) -> SplitPlan | None:
    """Greedy fill down the ranking (R-05). Each line takes what its stock allows, up to what is still needed."""
    remaining = need
    lines: list[Option] = []
    for o in ranked:
        if remaining <= 0:
            break
        if o.content is None or o.qty is None:
            continue
        want = _whole_up(remaining / o.content, o.plan.step if o.plan else None)
        take = min(want, o.max_qty) if o.max_qty is not None else want
        if take <= 0:
            continue
        line = Option(
            product_id=o.product_id,
            record=o.record,
            offer=o.offer,
            plan=o.plan,
            variant=o.variant,
            qty=take,
            content=o.content,
            max_qty=o.max_qty,
            gate="partial" if take < want else None,
            flags=[*o.flags, "SPLIT"],
            signals=o.signals,
            contributions=o.contributions,
            score=o.score,
            otif=o.otif,
            band=o.band,
            reliability=o.reliability,
            reliability_estimated=o.reliability_estimated,
            carbon=o.carbon,
            rank=o.rank,
            split_line=len(lines) + 1,
        )
        lines.append(line)
        remaining -= take * o.content
    if not lines:
        return None
    covered = sum((ln.qty * ln.content for ln in lines if ln.qty and ln.content), Decimal(0))
    return SplitPlan(
        lines=lines,
        need=need,
        unit=unit,
        covered=_norm(covered),
        shortfall=_norm(max(Decimal(0), need - covered)),
        total_net=sum((ln.total_net or Decimal(0) for ln in lines), Decimal(0)),
    )


# ---- explanations (R-06, W-05) --------------------------------------------------------------


def _stock_text(o: Option) -> tuple[str, str]:
    kind = o.offer.qty_kind
    ufi, uen = o.unit, o.unit
    if kind == "untracked":
        return "Valio Aimon varastosta, määrää ei seurata", "from Valio Aimo stock, quantity not tracked"
    if kind == "exact" and o.offer.qty is not None:
        n = o.offer.qty
        return (
            f"Valio Aimon varastosta, saatavilla {fi_num(n)} {ufi}",
            f"from Valio Aimo stock, {en_num(n)} {uen} available",
        )
    if kind == "terminal":
        return "suoraan toimittajalta, määrää ei ole vahvistettu", "direct from the supplier, quantity not confirmed"
    return "varastotilanne tuntematon", "stock unknown"


def _warning_texts(o: Option, need_unit: str) -> list[tuple[str, str]]:
    ufi, uen = UNIT_WORD[need_unit]
    out: list[tuple[str, str]] = []
    flags = set(o.flags)
    plan = o.plan
    content = o.content
    if "UNIT_MISMATCH" in flags and plan and content is not None:
        out.append(
            (
                f"Valio Aimo myy tätä yksikössä {o.unit} ({fi_num(content)} {ufi}), ei luettelon yksikössä "
                f"{plan.catalog_unit}",
                f"The API sells this per {o.unit} ({en_num(content)} {uen} each), not per {plan.catalog_unit} as "
                "in the catalogue",
            )
        )
    if "CONTENT_CONFLICT" in flags and content is not None:
        out.append(
            (
                f"pakkauskoon lähteet ovat ristiriidassa; käytetään {fi_num(content)} {ufi} / {o.unit}",
                f"content sources disagree; {en_num(content)} {uen} per {o.unit} is used",
            )
        )
    if "NEEDS_REVIEW" in flags:
        out.append(
            (
                "pakkauskoko on vain yhdestä lähteestä, joten ihmisen pitää vahvistaa se",
                "the pack content comes from one source only, so a person should confirm it",
            )
        )
    if o.split_line is None:
        total = o.total_content
        if total is not None and o.qty is not None and plan is not None:
            over = _norm(total - plan.need_amount)
            pct = (over / plan.need_amount * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if over > 0:
                out.append(
                    (
                        f"pyöristys täysiin yksiköihin antaa {fi_num(over)} {ufi} ylimääräistä ({fi_num(pct)} %)",
                        f"rounding up to whole units gives {en_num(over)} {uen} more than needed ({en_num(pct)} %)",
                    )
                )
    if plan and plan.step and plan.step > 1 and plan.api_unit != "KG":
        out.append(
            (f"tilauserä on {fi_num(plan.step)} {o.unit}", f"it is ordered in steps of {en_num(plan.step)} {o.unit}")
        )
    if plan and plan.api_unit == "KG" and plan.step and plan.step > Decimal("0.01"):
        out.append((f"tilauserä on {fi_num(plan.step)} kg", f"it is ordered in steps of {en_num(plan.step)} kg"))
    if "CATCH_WEIGHT" in flags:
        out.append(("laskutetaan todellisen painon mukaan", "it is invoiced by the actual weight delivered"))
    if "NET_ABOVE_LIST" in flags:
        out.append(
            (
                "asiakashinta on listahintaa korkeampi, mikä vaatii hyväksynnän",
                "the customer price is above the list price, which needs approval",
            )
        )
    if "DEPOSIT_NOT_PRICED" in flags:
        out.append(
            ("pantti ei sisälly hintaan ja vahvistetaan erikseen", "the deposit is not included and is to be confirmed")
        )
    if "CUTOFF_ESTIMATED" in flags:
        out.append(
            (
                "tilausaika on arvio tavallisesta toimitusajasta, joten se pitää vahvistaa",
                "the order-by time is estimated from the usual lead time, so it must be confirmed",
            )
        )
    if o.offer.validity == "unknown":
        out.append(("hinnan voimassaoloaika puuttuu", "the price has no validity dates"))
    if "VARIANT" in flags:
        out.append(
            (
                "tämä on muunnelma (esim. kahvimaito tai annospakkaus)",
                "this is a variant (for example coffee milk or portion packs)",
            )
        )
    return out


def _carbon_text(o: Option, need_unit: str) -> tuple[str, str]:
    if o.carbon is None:
        return "Hiilijalanjälkeä ei tiedetä.", "Carbon footprint unknown."
    cf = Decimal(str(o.carbon))
    f = f"Hiilijalanjälki noin {fi_num(cf)} kg CO2e/kg (kategorian keskiarvo)"
    e = f"Carbon about {en_num(cf)} kg CO2e/kg (category average)"
    total = o.total_content
    if total is not None and need_unit in ("L", "KG"):
        co2 = cf * total
        co2 = co2.quantize(Decimal(10), rounding=ROUND_HALF_UP) if co2 >= 100 else co2.quantize(Decimal("0.1"))
        f += f", yhteensä noin {fi_num(co2)} kg CO2e"
        e += f", about {en_num(co2)} kg CO2e"
        if need_unit == "L":
            f += " (oletus 1 kg litrassa)"
            e += " (assuming 1 kg per litre)"
    return f + ".", e + "."


def _tradeoff(o: Option, best: Option) -> tuple[str, str]:
    fi_parts: list[str] = []
    en_parts: list[str] = []
    if o.total_net is not None and best.total_net is not None:
        d = o.total_net - best.total_net
        if d > 0:
            fi_parts.append(f"+{fi_money(d)} €")
            en_parts.append(f"+EUR {en_money(d)}")
        elif d < 0:
            fi_parts.append(f"{fi_money(-d)} € edullisempi")
            en_parts.append(f"EUR {en_money(-d)} cheaper")
        else:
            fi_parts.append("sama hinta")
            en_parts.append("same price")
    if o.otif < best.otif - 0.005:
        fi_parts.append(
            f"heikompi toimitusvarmuus ({fi_num(round(Decimal(o.otif), 2))} vs {fi_num(round(Decimal(best.otif), 2))})"
        )
        en_parts.append(f"lower delivery confidence ({o.otif:.2f} vs {best.otif:.2f})")
    elif o.otif > best.otif + 0.005:
        fi_parts.append(
            f"varmempi toimitus ({fi_num(round(Decimal(o.otif), 2))} vs {fi_num(round(Decimal(best.otif), 2))})"
        )
        en_parts.append(f"safer delivery ({o.otif:.2f} vs {best.otif:.2f})")
    if o.reliability_estimated and not best.reliability_estimated:
        fi_parts.append("toimitusvarmuus on vain arvio")
        en_parts.append("its reliability is only estimated")
    if o.carbon is not None and best.carbon is not None and o.carbon != best.carbon:
        fi_parts.append(f"hiili {fi_num(Decimal(str(o.carbon)))} vs {fi_num(Decimal(str(best.carbon)))} kg CO2e/kg")
        en_parts.append(f"carbon {en_num(Decimal(str(o.carbon)))} vs {en_num(Decimal(str(best.carbon)))} kg CO2e/kg")
    if o.offer.logistic_model != best.offer.logistic_model and o.offer.logistic_model == "Terminal":
        fi_parts.append("toimittajalta, määrää ei vahvistettu")
        en_parts.append("from the supplier, quantity not confirmed")
    same = (
        o.offer.logistic_model == best.offer.logistic_model
        and o.offer.qty_kind == best.offer.qty_kind
        and o.offer.order_by == best.offer.order_by
        and o.reliability == best.reliability
        and o.reliability_estimated == best.reliability_estimated
    )
    if same:
        fi_parts.append("sama varastotilanne, tilausaika ja toimitusvarmuus")
        en_parts.append("same stock status, cut-off and reliability")
    return "Ero PARHAASEEN: " + "; ".join(fi_parts) + ".", "Trade-off vs BEST: " + "; ".join(en_parts) + "."


def explain(
    o: Option,
    *,
    need: Decimal,
    need_unit: str,
    need_date: date,
    now: datetime,
    best: Option | None,
    n_full: int,
    profile: str,
    split_of: int | None = None,
) -> Msg:
    """R-06 template with the live numbers (W-05)."""
    ufi, uen = UNIT_WORD[need_unit]
    if split_of:
        label_fi, label_en = f"OSA {o.split_line}/{split_of}", f"SPLIT {o.split_line}/{split_of}"
    elif o.tier in TIER_LABEL:
        label_fi, label_en = TIER_LABEL[o.tier]
    else:
        label_fi, label_en = "MUU", "OTHER"
    if o.tags:
        label_fi += " (" + ", ".join(TAG_TEXT[t][0] for t in o.tags) + ")"
        label_en += " (" + ", ".join(TAG_TEXT[t][1] for t in o.tags) + ")"
    qty = o.qty or Decimal(0)
    total = o.total_content or Decimal(0)
    net = o.total_net or Decimal(0)
    f = f"{label_fi}: {quoted(o.name)} [{o.product_id}], {o.vendor}. {fi_num(qty)} × {o.unit} = {fi_num(total)} {ufi}"
    e = f"{label_en}: {quoted(o.name)} [{o.product_id}], {o.vendor}. {en_num(qty)} × {o.unit} = {en_num(total)} {uen}"
    case = o.plan.case_alternative if o.plan else None
    if case is not None and case.exact:
        f += f" (= {fi_num(case.cases)} × {case.unit}, {fi_num(case.api_units_per_case)} {o.unit} / {case.unit})"
        e += f" (= {en_num(case.cases)} × {case.unit} of {en_num(case.api_units_per_case)})"
    f += f", {fi_money(net)} € alv 0 %"
    e += f", EUR {en_money(net)} excl. VAT"
    price = o.offer.price
    if o.total_gross is not None and price is not None and price.tax_rate is not None:
        f += f" ({fi_money(o.total_gross)} € sis. alv {fi_num(price.tax_rate)} %)"
        e += f" (EUR {en_money(o.total_gross)} incl. {en_num(price.tax_rate)} % VAT)"
    ppc = o.price_per_content
    if ppc is not None:
        f += f", {fi_money(ppc)} €/{ufi}"
        e += f", {en_money(ppc)} EUR/{uen}"
    if price is not None and price.net_price_found and price.valid_to is not None and price.valid_to.year < 9999:
        f += f", asiakashinta voimassa {_en_date(price.valid_to)} asti"
        e += f", customer price valid to {_en_date(price.valid_to)}"
    f += "."
    e += "."
    sfi, sen = _stock_text(o)
    ob = o.offer.order_by
    if ob is not None:
        left = _hours(ob - now)
        est_fi, est_en = (", arvio", ", estimated") if o.offer.order_by_estimated else ("", "")
        f += f" Toimitus {day_fi(need_date)} {sfi}; tilattava viimeistään {at_fi(ob)} ({fi_dec(left)} h aikaa{est_fi})."
        e += f" Delivery {day_en(need_date)} {sen}; order by {at_en(ob)} ({left} h left{est_en})."
    rel = o.reliability
    if rel is not None:
        src_fi, src_en = ("arvio", "estimated") if o.reliability_estimated else ("tuotehistoria", "product history")
        f += f" Toimitusvarmuus {fi_dec(Decimal(str(rel)).quantize(CENT))} ({src_fi})."
        e += f" Delivery reliability {Decimal(str(rel)).quantize(CENT)} ({src_en})."
    cfi, cen = _carbon_text(o, need_unit)
    f += " " + cfi
    e += " " + cen
    if split_of:
        firm = o.offer.qty_kind == "exact"
        f += " Varma rivi." if firm else " Määrää ei ole vahvistettu."
        e += " A firm line." if firm else " Quantity not confirmed."
    elif best is None or o is best:
        need_fi, need_en = f"{fi_num(need)} {ufi}", f"{en_num(need)} {uen}"
        n_fi = f"{n_full} vaihtoehdosta" if n_full != 1 else "ainoasta vaihtoehdosta"
        if "lowest price" in o.tags:
            f += (
                f" Miksi ensimmäinen: edullisin {n_fi}, jotka voivat toimittaa koko määrän ({need_fi}) "
                f"{day_fi(need_date)}."
            )
            e += (
                f" Why first: cheapest of the {n_full} {_plural(n_full, 'option', 'options')} that can deliver the "
                f"full {need_en} on {day_en(need_date)}."
            )
        else:
            f += f" Miksi ensimmäinen: paras kokonaispisteet ({profile}) {n_fi}, jotka voivat toimittaa koko määrän."
            e += (
                f" Why first: the best overall score ({profile} weighting) of the {n_full} "
                f"{_plural(n_full, 'option', 'options')} that can deliver the full {need_en} on {day_en(need_date)}."
            )
    else:
        tf, te = _tradeoff(o, best)
        f += " " + tf
        e += " " + te
    warnings = _warning_texts(o, need_unit)
    if warnings:
        f += " Huom: " + "; ".join(w[0] for w in warnings) + "."
        e += " Note: " + "; ".join(w[1] for w in warnings) + "."
    if o.offer.approve_by is not None:
        f += f" Hyväksyttävä viimeistään {at_fi(o.offer.approve_by)}."
        e += f" Approve before {at_en(o.offer.approve_by)}."
    return Msg(fi=fi_text(f), en=e)


def refusal_reason(o: Option, need: Decimal, need_unit: str, need_date: date) -> Msg:
    ufi, uen = UNIT_WORD[need_unit]
    off = o.offer
    supplier = off.logistic_model == "Terminal"
    who_fi, who_en = ("Toimittajan", "supplier") if supplier else ("Valio Aimon", "Valio Aimo")
    still_fi = still_en = ""
    if off.available_date is not None and off.available_date <= need_date:
        still_fi = f", vaikka järjestelmä näyttää yhä toimituksen {day_fi(off.available_date)}"
        still_en = f", although the system still shows delivery on {day_en(off.available_date)}"
    g = o.gate
    if g == "unknown_id":
        f, e = "Tuntematon tuotenumero.", "Unknown product id."
    elif g == "not_deliverable":
        f, e = "Ei toimitettavissa millekään päivälle.", "Cannot be delivered on any date."
    elif g == "sales_blocked":
        f, e = "Tuotteen myynti on estetty.", "Sales of this product are blocked."
    elif g == "out_of_stock":
        f, e = "Loppu varastosta.", "Out of stock."
    elif g == "late":
        days = off.late_days or 0
        avail = off.available_date
        f = f"Aikaisin toimitus {day_fi(avail) if avail else '?'}, {days} pv tarvepäivän jälkeen."
        e = (
            f"Earliest delivery {day_en(avail) if avail else '?'}, "
            f"{days} {_plural(days, 'day', 'days')} after the need date."
        )
    elif g == "cutoff_passed" and off.order_by is not None:
        f = f"{who_fi} tilausaika toimitukseen {day_fi(need_date)} päättyi {at_fi(off.order_by)}{still_fi}."
        e = f"The {who_en} cut-off for delivery on {day_en(need_date)} passed on {at_en(off.order_by)}{still_en}."
    elif g == "cutoff_too_close" and off.order_by is not None and off.approve_by is not None:
        f = (
            f"Tilausaika päättyy {at_fi(off.order_by)}, eikä hyväksynnälle jää aikaa "
            f"(hyväksyttävä viimeistään {at_fi(off.approve_by)})."
        )
        e = (
            f"The cut-off is {at_en(off.order_by)}, which leaves no time for approval "
            f"(approve-by {at_en(off.approve_by)} has passed)."
        )
    elif g == "no_price":
        f, e = "Valio Aimo ei antanut hintaa.", "Valio Aimo returned no price."
    elif g == "price_not_valid" and off.price is not None:
        to = off.price.valid_to
        f = f"Asiakashinta on voimassa {_en_date(to) if to else '?'} asti, ei toimituspäivänä {day_fi(need_date)}."
        e = (
            f"The customer price is valid to {_en_date(to) if to else '?'}, "
            f"not on the delivery date {day_en(need_date)}."
        )
    elif g == "not_comparable":
        dim = o.plan.content.dim if o.plan else None
        if dim and dim != need_unit and o.plan and "DIMENSION_MISMATCH" in o.plan.flags:
            dfi, den = UNIT_WORD.get(dim, (dim, dim))
            f = f"Pakkauskoko tiedetään yksikössä {dfi}, mutta tarve on yksikössä {ufi}, joten sitä ei voi verrata."
            e = f"Its content is known in {den}, but the need is in {uen}, so it cannot be compared."
        else:
            f = "Pakkauskokoa ei tiedetä, joten määrää ei voi laskea."
            e = "Its content per unit is unknown, so the quantity cannot be planned."
    elif g == "variant":
        f = "Muunnelma (esim. kahvimaito, Cafè tai annospakkaus): tarjotaan vain, jos hyväksyt muunnelmat."
        e = "A variant (for example coffee milk, Cafè or portion packs): offered only if you accept variants."
    elif g == "partial":
        have = o.max_qty or Decimal(0)
        covered = have * (o.content or Decimal(0))
        f = f"Varastossa vain {fi_num(have)} × {o.unit} ({fi_num(covered)} {ufi}); tarvitaan {fi_num(need)} {ufi}."
        e = f"Only {en_num(have)} × {o.unit} in stock ({en_num(covered)} {uen}); {en_num(need)} {uen} are needed."
    else:
        f, e = "Ei tarjolla.", "Not offered."
    if o.variant and g != "variant":
        f += " Lisäksi tuote on muunnelma."
        e += " It is also a variant."
    return Msg(fi=fi_text(f), en=e)


# ---- assembling the response ----------------------------------------------------------------


def _to_offer(o: Option, offer_set_id: str, msg: Msg, need_unit: str, need_date: date) -> Offer:
    suffix = f":split{o.split_line}" if o.split_line else ""
    return Offer(
        offer_id=f"{offer_set_id}:{o.product_id}{suffix}",
        tier=o.tier if not o.split_line else "other",
        product_id=o.product_id,
        name_fi=o.name,
        api_unit=o.unit,
        qty=int(o.qty or 0),
        content_total=str(o.total_content),
        unit_price_net=money(o.unit_price or Decimal(0)),
        total_net=money(o.total_net or Decimal(0)),
        price_per_base_unit=money(o.price_per_content or Decimal(0)),
        base_unit=need_unit,  # type: ignore[arg-type]
        delivery_date=need_date.isoformat(),
        order_by=o.offer.order_by.isoformat() if o.offer.order_by else "",
        stock=o.stock,
        stock_qty=int(o.offer.qty) if o.stock == "known" and o.offer.qty is not None else None,
        flags=o.contract_flags(),
        explanation=msg,
    )


def _summary(
    req: OffersRequest,
    need: Decimal,
    need_date: date,
    n_candidates: int,
    n_full: int,
    offered: list[Option],
    refused: list[Option],
    split: SplitPlan | None,
    variants_held: int,
) -> tuple[Msg, Any]:
    ufi, uen = UNIT_WORD[req.unit]
    fi_parts: list[str] = []
    en_parts: list[str] = []
    found_fi = "1 sopivan tuotteen" if n_candidates == 1 else f"{n_candidates} sopivaa tuotetta"
    found_en = "1 matching product" if n_candidates == 1 else f"{n_candidates} matching products"
    need_fi, need_en = f"{fi_num(need)} {ufi}", f"{en_num(need)} {uen}"
    reason_code = None
    if offered:
        best = offered[0]
        held_fi = ""
        if variants_held == 1:
            held_fi = " (1 niistä on muunnelma, jota et ole hyväksynyt)"
        elif variants_held:
            held_fi = f" ({variants_held} niistä on muunnelmia, joita et ole hyväksynyt)"
        held_en = (
            f" ({variants_held} of them {_plural(variants_held, 'a variant', 'variants')} you have not accepted)"
            if variants_held
            else ""
        )
        fi_parts.append(
            f"Löysin {found_fi}; {n_full} voidaan toimittaa koko määrältä ({need_fi}) {day_fi(need_date)}{held_fi}."
        )
        en_parts.append(f"I found {found_en}; {n_full} can deliver the full {need_en} on {day_en(need_date)}{held_en}.")
        ob = best.offer.order_by
        fi_parts.append(
            f"Paras vaihtoehto on {fi_num(best.qty or 0)} × {best.unit} {quoted(best.name)}, "
            f"{fi_money(best.total_net or Decimal(0))} € "
            f"alv 0 % ({fi_money(best.price_per_content or Decimal(0))} €/{ufi})"
            + (f", tilattava viimeistään {at_fi(ob)}." if ob else ".")
        )
        en_parts.append(
            f"The best option is {en_num(best.qty or 0)} × {best.unit} {quoted(best.name)}, "
            f"EUR {en_money(best.total_net or Decimal(0))} "
            f"excl. VAT ({en_money(best.price_per_content or Decimal(0))} EUR/{uen})"
            + (f", to be ordered by {at_en(ob)}." if ob else ".")
        )
    elif n_candidates:
        fi_parts.append(
            f"Löysin {found_fi}, mutta yksikään ei voi toimittaa koko määrää ({need_fi}) {day_fi(need_date)}."
        )
        en_parts.append(f"I found {found_en}, but none can deliver the full {need_en} on {day_en(need_date)}.")
    else:
        fi_parts.append(f"En löytänyt luettelosta tuotetta, joka sopii tarpeeseen {quoted(req.query)}.")
        en_parts.append(f"I found no catalogue product that matches {quoted(req.query)}.")
        reason_code = "not_found"
    if split is not None:
        n = len(split.lines)
        parts_fi = " + ".join(f"{fi_num(o.qty or 0)} × {o.product_id}" for o in split.lines)
        parts_en = " + ".join(f"{en_num(o.qty or 0)} × {o.product_id}" for o in split.lines)
        fi_parts.append(
            f"Jakoehdotus {n} tuotteesta: {parts_fi} = {fi_num(split.covered)} {ufi}, "
            f"{fi_money(split.total_net)} € alv 0 %."
        )
        en_parts.append(
            f"Split proposal over {n} {_plural(n, 'product', 'products')}: {parts_en} = {en_num(split.covered)} {uen}, "
            f"EUR {en_money(split.total_net)} excl. VAT."
        )
        if split.shortfall > 0:
            fi_parts.append(f"{fi_num(split.shortfall)} {ufi} jää kattamatta.")
            en_parts.append(f"{en_num(split.shortfall)} {uen} remain uncovered.")
        fi_parts.append("Jaettu toimitus vaatii hyväksynnän.")
        en_parts.append("A split delivery needs approval.")
    cut = [o for o in refused if o.gate in ("cutoff_passed", "cutoff_too_close")]
    if cut:
        terminal = [o for o in cut if o.offer.logistic_model == "Terminal"]
        latest = max((o.offer.order_by for o in cut if o.offer.order_by), default=None)
        n = len(cut)
        if len(terminal) == n:
            fi_parts.append(
                f"{n} vaihtoehtoa tulee toimittajan varastosta, ja niiden tilausaika on jo mennyt"
                + (f" (viimeisin {at_fi(latest)})" if latest else "")
                + ", vaikka järjestelmä näyttää yhä toimituspäivän."
            )
            en_parts.append(
                f"{n} {_plural(n, 'option comes', 'options come')} from supplier warehouses and their cut-off has "
                "already passed" + (f" (latest {at_en(latest)})" if latest else "") + ", although the system still "
                "shows the delivery date."
            )
        else:
            fi_parts.append(f"{n} vaihtoehdon tilausaika on jo mennyt.")
            en_parts.append(f"The cut-off has already passed for {n} {_plural(n, 'option', 'options')}.")
        cheaper = [
            o
            for o in cut
            if offered and o.price_per_content is not None and o.price_per_content < (offered[0].price_per_content or 0)
        ]
        if cheaper:
            c = min(cheaper, key=lambda o: (o.price_per_content, o.product_id))
            fi_parts.append(
                f"Edullisin niistä olisi ollut {quoted(c.name)} [{c.product_id}], "
                f"{fi_money(c.price_per_content or Decimal(0))} €/{ufi}."
            )
            en_parts.append(
                f"The cheapest of them would have been {quoted(c.name)} [{c.product_id}], "
                f"{en_money(c.price_per_content or Decimal(0))} EUR/{uen}."
            )
    if not offered and split is None and refused:
        if cut:
            reason_code = "cutoff_passed"
        elif any(o.gate == "out_of_stock" or o.gate == "partial" for o in refused):
            reason_code = "out_of_stock"
        else:
            reason_code = "not_deliverable"
        partial = sum(1 for o in refused if o.gate == "partial")
        if partial:
            fi_parts.append(f"Varasto ei riitä koko määrään {partial} tuotteella.")
            en_parts.append(f"Stock does not cover the full amount for {partial} of them.")
    if variants_held and not req.allow_variants:
        fi_parts.append("Kerro, jos muunnelmat (esim. kahvimaito tai annospakkaukset) käyvät.")
        en_parts.append("Say if variants (such as coffee milk or portion packs) are acceptable.")
    return Msg(fi=fi_text(" ".join(fi_parts)), en=" ".join(en_parts)), reason_code


def _now(as_of: str | datetime | Clock) -> datetime:
    if callable(as_of):
        return to_helsinki(as_of())
    return to_helsinki(parse_api_time(as_of) if isinstance(as_of, str) else as_of)


def _empty(endpoint: Literal["price", "availability"], need_date: str) -> ApiResult:
    return ApiResult(
        endpoint=endpoint, customer="", requested_date=need_date, entries={}, entry_evidence={}, evidence=[]
    )


def build_offer_set(
    req: OffersRequest,
    found: SearchResult,
    availability: ApiResult,
    price: ApiResult,
    *,
    as_of: str | datetime | Clock,
    conn: sqlite3.Connection | None = None,
    buffer: timedelta = DEFAULT_BUFFER,
    profile: str | None = None,
    weights: Weights | None = None,
    allow_split: bool = True,
    offer_set_id: str | None = None,
) -> OfferSet:
    """Gates, signals, ranking, good-better-best, split and explanations over already-fetched results (no I/O
    except the category reliability lookup on `conn`)."""
    now = _now(as_of)
    need_date = date.fromisoformat(req.need_date)
    need = _norm(_q(req.amount))
    profile = profile or PREFERENCE_PROFILE.get(req.preference, "balanced")
    weights = weights or PROFILES[profile]
    interp = found.interpretation
    heads = [h for h in interp.get("heads") or [] if h not in consent_heads_from(interp)]
    claims = list(interp.get("must_claims") or [])
    banned = list(interp.get("banned_allergens") or [])
    warnings: list[str] = list(found.warnings)

    rel_cache: dict[str, float] = {}
    options: list[Option] = []
    for hit in found.hits:
        record = hit.record
        if not _diet_ok(record, claims, banned):
            warnings.append(f"{hit.product_id} dropped: its record does not meet the diet constraints")
            continue
        variant = is_variant(record, heads, req.query)
        o = _assess(hit.product_id, record, need, req.unit, need_date, availability, price, now, buffer, variant)
        if o.gate is None and variant and not req.allow_variants:
            o.gate = "variant"
        if o.gate == "partial" and variant and not req.allow_variants:
            o.gate = "variant"
        rel = (record.get("delivery_reliability") or {}).get("value")
        if rel is None:
            o.reliability = _category_reliability(conn, record.get("category") or "", rel_cache)
            o.reliability_estimated = True
        else:
            o.reliability = float(rel)
        cf = (record.get("carbon") or {}).get("kg_co2e_per_kg")
        o.carbon = None if cf is None else float(cf)
        options.append(o)

    rankable = [o for o in options if o.gate in (None, "partial")]
    _signals(rankable, now, weights)
    rankable.sort(key=_rank_key)
    for i, o in enumerate(rankable, 1):
        o.rank = i
    full = [o for o in rankable if o.gate is None]
    # Good-better-best over the options that cover the need (R-05).
    picks: list[Option] = []
    for o in full:
        if len(picks) == 3:
            break
        if not picks or _real_alternative(o, picks):
            o.tier = ("best", "better", "good")[len(picks)]  # type: ignore[assignment]
            picks.append(o)
    _tags(full, picks, bool(claims or banned))

    split: SplitPlan | None = None
    if allow_split and rankable and (not full or rankable[0].gate == "partial"):
        split = _split(rankable, need, req.unit)

    if offer_set_id is None:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "req": req.model_dump(mode="json"),
                    "as_of": now.isoformat(),
                    "evidence": sorted({h for o in options for h in o.offer.evidence}),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        offer_set_id = "OS-" + digest[:8].upper()

    best = picks[0] if picks else None
    ordered_full = [*picks, *(o for o in full if o not in picks)]
    contract_options: list[Offer] = []
    for o in ordered_full[: req.limit]:
        msg = explain(
            o, need=need, need_unit=req.unit, need_date=need_date, now=now, best=best, n_full=len(full), profile=profile
        )
        contract_options.append(_to_offer(o, offer_set_id, msg, req.unit, need_date))
    if split is not None:
        for line in split.lines:
            msg = explain(
                line,
                need=need,
                need_unit=req.unit,
                need_date=need_date,
                now=now,
                best=None,
                n_full=len(full),
                profile=profile,
                split_of=len(split.lines),
            )
            contract_options.append(_to_offer(line, offer_set_id, msg, req.unit, need_date))
    split_ids = {ln.product_id for ln in split.lines} if split else set()
    refused = [o for o in options if o.gate is not None and not (o.gate == "partial" and o.product_id in split_ids)]
    not_offered = [
        NotOffered(
            product_id=o.product_id,
            name_fi=o.name,
            flags=o.contract_flags(),
            reason=refusal_reason(o, need, req.unit, need_date),
        )
        for o in refused
    ]

    counts = dict.fromkeys(COUNT_KEYS, 0)
    counts["candidates"] = len(options)
    feasible_full = [o for o in options if o.base_gate is None]
    counts["on_time_full"] = len(feasible_full)
    counts["stock_full"] = sum(1 for o in feasible_full if o.offer.logistic_model == "Stock")
    counts["terminal_full"] = sum(1 for o in feasible_full if o.offer.logistic_model == "Terminal")
    counts["offered"] = min(len(full), req.limit)
    counts["split_lines"] = len(split.lines) if split else 0
    for o in options:
        if o.gate is not None:
            counts[GATE_COUNT.get(o.gate, o.gate)] += 1
            if o.gate == "cutoff_passed" and o.offer.logistic_model == "Terminal":
                counts["cutoff_passed_terminal"] += 1
    variants_held = sum(1 for o in feasible_full if o.gate == "variant")
    message, reason_code = _summary(
        req, need, need_date, len(options), len(feasible_full), ordered_full, refused, split, variants_held
    )
    if any(o.stock == "untracked" for o in ordered_full[: req.limit]):
        warnings.append("Stock is not tracked for some options: shown as 'not tracked', not as a number.")
    if any(o.reliability_estimated for o in ordered_full[: req.limit]):
        warnings.append(
            f"Delivery reliability is estimated for some options (category mean shrunk to {GLOBAL_RELIABILITY}, "
            f"capped at {RELIABILITY_CAP})."
        )
    for res in (availability, price):
        for w in res.warnings:
            if w == "REPLAY_DATE_SUBSTITUTED":
                warnings.append("replay: some answers come from the 2026-11-16 recording (the snapshot is frozen)")
            elif w == "REPLAY_NOT_RECORDED":
                warnings.append("replay: some products were not recorded and have no availability or price")
            else:
                warnings.append(w)
    response = OffersResponse(
        offer_set_id=offer_set_id,
        need={
            "amount": req.amount,
            "unit": req.unit,
            "need_date": req.need_date,
            "claims": claims,
            "heads": interp.get("heads") or [],
            "exclude": req.exclude,
            "must_not_allergens": req.must_not_allergens,
            "banned_allergens": banned,
            "temperature": req.temperature,
            "preference": req.preference,
            "profile": profile,
            "allow_variants": req.allow_variants,
        },
        as_of=now.isoformat(),
        options=contract_options,
        not_offered=not_offered,
        counts=counts,
        message_for_user=message,
        reason_code=reason_code,
        warnings=list(dict.fromkeys(warnings)),
    )
    order = {id(o): i for i, o in enumerate(rankable)}
    options.sort(key=lambda o: (order.get(id(o), len(order)), o.product_id))
    return OfferSet(
        response=response,
        options=options,
        split=split,
        profile=profile,
        weights=weights,
        interpretation=interp,
        evidence=sorted({e.sha256 for r in (availability, price) for e in r.evidence}),
    )


def consent_heads_from(interp: Mapping[str, Any]) -> list[str]:
    """The consent heads get_offers added to the search (kept out of the variant check's plain heads)."""
    return list(interp.get("consent_heads") or [])


# ---- the tool -------------------------------------------------------------------------------


class PriceSource(Protocol):
    """What get_offers needs from the M3 client (ValioClient fits)."""

    async def availability(self, ids: Iterable[object], requested_date: date | str) -> ApiResult: ...

    async def price(self, ids: Iterable[object], requested_date: date | str) -> ApiResult: ...


SHORTLIST = MAX_LIMIT  # the search's own maximum; the API is called for these ids only


def shortlist(conn: sqlite3.Connection, req: OffersRequest, *, limit: int = SHORTLIST) -> SearchResult:
    """The M4 search for the need, plus the variant heads a buyer may accept (marked in the interpretation)."""
    args = (req.exclude, req.must_claims, req.must_not_allergens, req.temperature, limit)
    found = search(conn, req.query, req.heads, *args)
    heads = list(found.interpretation.get("heads") or [])
    extra = consent_heads(heads) if found.mode == "heads" else []
    if extra:
        found = search(conn, req.query, [*heads, *extra], *args)
        # Found only through a consent head and also flavoured or processed ('kahvimaitojuoma vanilja'): another
        # product, not a variant of the need (W-01 excludes it), so it is dropped.
        plain, consent = parse_heads(heads), parse_heads(extra)
        asked = [*read_query(req.query).content, *heads, *extra]
        keep: list[Hit] = []
        dropped = 0
        for h in found.hits:
            name = h.record.get("name_fi") or ""
            m = match_head(name, consent)
            if not isinstance(match_head(name, plain), HeadMatch) and isinstance(m, HeadMatch):
                if _variant(m, name, _variant_words(asked)) > 0:
                    dropped += 1
                    continue
            keep.append(h)
        found.hits = keep
        found.total_matches -= dropped
        if dropped:
            found.interpretation["dropped"] = {**found.interpretation.get("dropped", {}), "flavoured_variant": dropped}
    found.interpretation["consent_heads"] = extra
    return found


async def get_offers(
    req: OffersRequest,
    *,
    conn: sqlite3.Connection,
    client: PriceSource,
    as_of: str | datetime | Clock,
    buffer: timedelta = DEFAULT_BUFFER,
    profile: str | None = None,
) -> OfferSet:
    """PLAN M5.1: search, then plan, then price and availability for the shortlisted ids, then the gates and the
    ranking. Valio client errors (ValioUnavailable, ReplayUnavailable) propagate: they are real failures."""
    found = shortlist(conn, req)
    ids = found.ids
    if ids:
        availability = await client.availability(ids, req.need_date)
        price = await client.price(ids, req.need_date)
    else:
        availability, price = _empty("availability", req.need_date), _empty("price", req.need_date)
    return build_offer_set(req, found, availability, price, as_of=as_of, conn=conn, buffer=buffer, profile=profile)


def get_offers_blocking(req: OffersRequest, **kwargs: Any) -> OfferSet:
    """get_offers from synchronous code with no running event loop (a sync FastAPI route runs in a worker thread)."""
    return asyncio.run(get_offers(req, **kwargs))


def build_product_offer(
    product_id: str,
    record: dict[str, Any],
    amount: float,
    unit: str,
    need_date: str,
    availability: ApiResult,
    price: ApiResult,
    *,
    as_of: str | datetime | Clock,
    conn: sqlite3.Connection | None = None,
    buffer: timedelta = DEFAULT_BUFFER,
    heads: Sequence[str] = (),
) -> OfferSet:
    """The one-product offer set behind price_product, over answers the caller already has (no I/O except the
    category reliability lookup on `conn`). The buyer chose this product, so a variant is not held back (`heads`,
    the need's product types, only mark it VARIANT) and no split is proposed."""
    req = OffersRequest(
        query=record.get("name_fi") or product_id,
        amount=amount,
        unit=unit,  # type: ignore[arg-type]
        need_date=need_date,
        allow_variants=True,
    )
    found = SearchResult(
        hits=[Hit(product_id=product_id, record=record)],
        total_matches=1,
        mode="heads",
        interpretation={"heads": list(heads)},
    )
    offer_set_id = (
        "OP-" + hashlib.sha256(f"{product_id}|{_norm(_q(amount))}|{unit}|{need_date}".encode()).hexdigest()[:8].upper()
    )
    return build_offer_set(
        req,
        found,
        availability,
        price,
        as_of=as_of,
        conn=conn,
        buffer=buffer,
        allow_split=False,
        offer_set_id=offer_set_id,
    )


def product_offer(res: OfferSet) -> tuple[Offer | None, NotOffered | None]:
    """price_product's answer from build_product_offer's offer set."""
    opt = res.options[0] if res.options else None
    if opt is None or opt.gate == "not_comparable":
        return None, None
    if res.response.options:
        return res.response.options[0], None
    return None, res.response.not_offered[0] if res.response.not_offered else None


async def price_product(
    product_id: str,
    amount: float,
    unit: str,
    need_date: str,
    *,
    conn: sqlite3.Connection,
    client: PriceSource,
    as_of: str | datetime | Clock,
    buffer: timedelta = DEFAULT_BUFFER,
    heads: Sequence[str] = (),
) -> tuple[Offer | None, NotOffered | None]:
    """One product priced for one need, as stubs.price_product: (offer, None) when it delivers the full amount,
    (None, why not) otherwise, and (None, None) when it is not in the catalogue or its content does not convert to
    `unit`. The buyer chose this product, so a variant is not held back (`heads`, the need's product types, only
    mark it VARIANT) and no split is proposed."""
    record = get_record(conn, product_id)
    if record is None:
        return None, None
    availability = await client.availability([product_id], need_date)
    price = await client.price([product_id], need_date)
    res = build_product_offer(
        product_id, record, amount, unit, need_date, availability, price, as_of=as_of, conn=conn, buffer=buffer,
        heads=heads,
    )  # fmt: skip
    return product_offer(res)


__all__ = [
    "PROFILES",
    "PREFERENCE_PROFILE",
    "Option",
    "OfferSet",
    "PriceSource",
    "SplitPlan",
    "Weights",
    "build_offer_set",
    "build_product_offer",
    "catalog_units",
    "consent_heads",
    "estimate_reliability",
    "explain",
    "get_offers",
    "get_offers_blocking",
    "is_variant",
    "price_product",
    "product_offer",
    "refusal_reason",
    "shortlist",
]
