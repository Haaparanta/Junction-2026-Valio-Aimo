"""Baskets: many products, one quote (docs/basket-plan.md M22.2).

A basket belongs to one buyer and lives in SQLite (B-02). Each line keeps its draft (what it asks for) and the
last priced snapshot. Every change prices the line again in exactly one function, BasketService.price, so the
gateway decides every number. Quotes, orders and approvals stay in StubState until M6 and M8.

The internal API below (create_basket, get, current, add_lines, update_line, choose_product, remove_line,
restore_line, quote, mark_quoted, mark_ordered, is_stale) is what the routes call, and what the sheet import, the photo
import and plan_dish build on: they turn rows, photo items or dish ingredients into LineDraft objects.
"""

import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .contract import (
    Basket,
    BasketLine,
    BasketLinePatch,
    BasketQuoteResponse,
    BasketResponse,
    Confidence,
    FlagNote,
    IsoDate,
    LineSource,
    LineStatus,
    Msg,
    NotOffered,
    Offer,
    OfferFlag,
    OffersRequest,
    Quote,
    SearchRequest,
    Unit,
)
from .db import Store
from .fmt import at_en, at_fi, clock_en, clock_fi, day_en, day_fi, fi, ids_en, ids_fi, money, num, quoted, to_helsinki
from .identity import Buyer, SettingsDep
from .settings import Settings
from .stubs import PRODUCTS, StubState, heads_for, invented_warnings, matches, rank, vat_of

MAX_LINES = 200
STATUSES: list[LineStatus] = list(get_args(LineStatus))
FLAG_ORDER: list[OfferFlag] = list(get_args(OfferFlag))
BLOCKING: set[OfferFlag] = {"CUTOFF_PASSED", "NOT_DELIVERABLE", "OUT_OF_STOCK", "PARTIAL_STOCK"}
ProductIdStr = Annotated[str, Field(pattern=r"^\d{6}$")]

# What each flag means for the buyer, and the next step (B-04). BasketLine.flag_notes carries these.
FLAG_TEXT: dict[OfferFlag, Msg] = {
    "CUTOFF_PASSED": Msg(
        fi="Tilausaika tälle toimituspäivälle on mennyt. Valitse myöhäisempi toimituspäivä.",
        en="The order-by time for this delivery date has passed. Choose a later delivery date.",
    ),
    "NOT_DELIVERABLE": Msg(
        fi="Tuotetta ei voi toimittaa millekään päivälle. Valitse toinen tuote tai poista rivi.",
        en="This product cannot be delivered on any date. Choose another product or remove the line.",
    ),
    "OUT_OF_STOCK": Msg(
        fi="Tuote on loppu varastosta. Valitse toinen tuote tai myöhäisempi päivä.",
        en="The product is out of stock. Choose another product or a later date.",
    ),
    "PARTIAL_STOCK": Msg(
        fi="Varastossa on vähemmän kuin tarvitset. Pienennä määrää tai valitse toinen tuote.",
        en="There is less in stock than you need. Lower the amount or choose another product.",
    ),
    "STOCK_UNTRACKED": Msg(
        fi="Varastosaldoa ei seurata, joten määrää ei näytetä numerona. Toimitus on silti mahdollinen.",
        en="Stock is not tracked for this product, so no quantity is shown. It can still be delivered.",
    ),
    "UNIT_MISMATCH": Msg(
        fi="Hinta ja määrä ovat tilausyksikössä, joka eroaa luettelon myyntiyksiköstä. Tarkista yksikkö.",
        en="Price and quantity are in an order unit that differs from the catalogue's sales unit. Check the unit.",
    ),
    "SALES_BLOCKED": Msg(
        fi="Tuotteen myynti on estetty. Valitse toinen tuote.",
        en="Sales of this product are blocked. Choose another product.",
    ),
    "VARIANT": Msg(
        fi="Tämä on muunnelma, kuten kahvimaito tai annospakkaus. Valitse se vain, jos se käy keittiöllesi.",
        en="This is a variant, such as coffee milk or portion packs. Choose it only if it suits your kitchen.",
    ),
    "NET_PRICE": Msg(
        fi="Hinta on asiakaskohtainen sopimushinta. Mitään ei tarvitse tehdä.",
        en="This is your customer contract price. Nothing to do.",
    ),
    "PRICE_NOT_VALID_FOR_DELIVERY_DATE": Msg(
        fi="Hinta ei ole voimassa toimituspäivänä. Valitse toinen päivä tai pyydä uusi tarjous.",
        en="The price is not valid on the delivery date. Choose another date or ask for a new quote.",
    ),
}

NEEDS_AMOUNT = Msg(
    fi="Anna määrä ja yksikkö: litrat (L), kilot (KG) tai kappaleet (PCS).",
    en="Give an amount and a unit: litres (L), kilograms (KG) or pieces (PCS).",
)
UNMATCHED = Msg(
    fi="Tuotetta ei löytynyt luettelosta. Poista rivi tai kokeile toista nimeä.",
    en="Not found in the catalogue. Remove the line or try another name.",
)
LOCKED = Msg(
    fi="Tämä kori on jo tilattu, eikä sitä voi enää muuttaa. Aloita uusi kori.",
    en="This basket is already ordered and can no longer change. Start a new basket.",
)
STALE_CONFIRM = Msg(
    fi="Kori on muuttunut tämän tarjouksen jälkeen, joten sitä ei voi vahvistaa. Pyydä uusi tarjous.",
    en="The basket changed after this quote, so it cannot be confirmed. Make a new quote.",
)
STALE_ORDER = Msg(
    fi="Kori on muuttunut tarjouksen jälkeen. Pyydä uusi tarjous ja vahvista se näytöltä.",
    en="The basket changed after this quote. Make a new quote and confirm it on screen.",
)


def msg_choice(n: int) -> Msg:
    return Msg(fi=f"Valitse yksi {n} vaihtoehdosta.", en=f"Choose one of {n} matches.")


def msg_unit(units: list[str], name: str | None = None) -> Msg:
    u = " tai ".join(units)
    if name:
        return Msg(
            fi=f"{quoted(name)} hinnoitellaan yksikössä {u}. Anna määrä yksikössä {u}.",
            en=f"{quoted(name)} is priced per {' or '.join(units)}. Give the amount in {' or '.join(units)}.",
        )
    return Msg(
        fi=f"Tähän tarpeeseen sopivat tuotteet myydään yksikössä {u}. Anna määrä yksikössä {u}.",
        en=f"The products for this need are sold per {' or '.join(units)}. Give the amount in {' or '.join(units)}.",
    )


def msg_cutoff(d: date) -> Msg:
    return Msg(
        fi=f"Tilausaika toimitukseen {day_fi(d)} on mennyt. Valitse myöhäisempi toimituspäivä.",
        en=f"The order-by time for delivery on {day_en(d)} has passed. Choose a later delivery date.",
    )


def msg_not_deliverable(d: date, name: str | None = None) -> Msg:
    if name:
        return Msg(
            fi=f"{quoted(name)} ei ole toimitettavissa {day_fi(d)} koko määrältä. "
            "Valitse toinen tuote tai poista rivi.",
            en=f"{quoted(name)} cannot deliver the full amount on {day_en(d)}. "
            "Choose another product or remove the line.",
        )
    return Msg(
        fi=f"Yhtäkään sopivaa tuotetta ei voi toimittaa {day_fi(d)} koko määrältä. "
        "Valitse toinen päivä tai poista rivi.",
        en=f"No matching product can deliver the full amount on {day_en(d)}. Choose another date or remove the line.",
    )


def msg_priced(o: Offer) -> Msg:
    d, ob = date.fromisoformat(o.delivery_date), datetime.fromisoformat(o.order_by)
    return Msg(
        fi=f"Hinnoiteltu: {o.qty} × {o.api_unit} {quoted(o.name_fi)}, {fi(o.total_net)} € alv 0 %. "
        f"Toimitus {day_fi(d)}, tilattava {at_fi(ob)} mennessä.",
        en=f"Priced: {o.qty} × {o.api_unit} {quoted(o.name_fi)}, EUR {o.total_net} excl. VAT. "
        f"Delivery {day_en(d)}; order by {at_en(ob)}.",
    )


# ---- drafts and snapshots ------------------------------------------------------------------------


class LineNeed(SearchRequest):
    """The search part of a need: an OffersRequest without amount, unit and need_date (those are the line's)."""

    preference: Literal["cheapest", "greenest", "most_reliable"] = OffersRequest.model_fields["preference"]
    allow_variants: bool = OffersRequest.model_fields["allow_variants"]


class LineDraft(BaseModel):
    """What a line asks for. The gateway prices the line from this again on every change.

    A line has a search need (voice, ui, dish), a pinned product (an exact sheet id, or the buyer's choice), or
    candidate products to choose from (a sheet or photo row with several matches). It may have none of them
    (unmatched) and no amount yet (needs_amount).
    """

    model_config = ConfigDict(extra="forbid")

    source: LineSource
    need_text: str  # the buyer's words, the sheet row's name or the dish ingredient
    raw_text: str | None = None  # exactly as read from a sheet row or a photo
    confidence: Confidence | None = None  # photo lines only
    need: LineNeed | None = None
    product_id: ProductIdStr | None = None
    candidates: list[ProductIdStr] = Field(default_factory=list)
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
    unit: Unit | None = None
    need_date: IsoDate = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: list[Msg] = Field(default_factory=list)

    @classmethod
    def from_offers_request(cls, req: OffersRequest, source: LineSource, product_id: str | None = None) -> "LineDraft":
        need = LineNeed(**{k: getattr(req, k) for k in LineNeed.model_fields})
        return cls(
            source=source,
            need_text=req.query,
            need=need,
            product_id=product_id,
            amount=req.amount,
            unit=req.unit,
            need_date=req.need_date,
        )

    def offers_request(self) -> OffersRequest:
        if self.need is None or self.amount is None or self.unit is None:
            raise ValueError("a search need with an amount and a unit is needed")
        return OffersRequest(**self.need.model_dump(), amount=self.amount, unit=self.unit, need_date=self.need_date)


class Snapshot(BaseModel):
    """A line's last priced result, stored as JSON next to its draft."""

    status: LineStatus
    product_id: str | None = None
    name_fi: str | None = None
    offer: Offer | None = None
    alternatives: list[Offer] = Field(default_factory=list)
    flags: list[OfferFlag] = Field(default_factory=list)
    message: Msg
    overshoot: str | None = None
    vat_rate: str | None = None
    line_vat: str | None = None
    line_gross: str | None = None


def need_key(d: LineDraft) -> str:
    """The normalised need, so an identical add (a retried tool call, a double click) finds its line."""

    def norm(xs: list[str], f: Any) -> list[str]:
        return sorted({f(x.strip()) for x in xs if x.strip()})

    n = d.need
    key = {
        "need": None
        if n is None
        else {
            "query": " ".join(n.query.casefold().split()),
            "heads": norm(n.heads, str.casefold),
            "exclude": norm(n.exclude, str.casefold),
            "must_claims": norm(n.must_claims, str.upper),
            "must_not_allergens": norm(n.must_not_allergens, str.upper),
            "temperature": n.temperature,
            "preference": n.preference,
            "allow_variants": n.allow_variants,
        },
        "product_id": d.product_id,
        "candidates": sorted(d.candidates),
        "amount": None if d.amount is None else num(Decimal(str(d.amount))),
        "unit": d.unit,
        "need_date": d.need_date,
    }
    return json.dumps(key, sort_keys=True, ensure_ascii=False)


def to_line(line_id: int, d: LineDraft, s: Snapshot) -> BasketLine:
    return BasketLine(
        line_id=line_id,
        source=d.source,
        need_text=d.need_text,
        raw_text=d.raw_text,
        confidence=d.confidence,
        product_id=s.product_id,
        name_fi=s.name_fi,
        amount=d.amount,
        unit=d.unit,
        need_date=d.need_date,
        offer=s.offer,
        alternatives=s.alternatives,
        status=s.status,
        flags=s.flags,
        flag_notes=[FlagNote(code=f, text=FLAG_TEXT[f]) for f in s.flags],
        message=s.message,
        overshoot=s.overshoot,
        vat_rate=s.vat_rate,
        line_vat=s.line_vat,
        line_gross=s.line_gross,
        notes=d.notes,
    )


Outcome = Literal["added", "duplicate", "changed", "unchanged", "unknown_offer", "removed", "restored", "locked"]


@dataclass(frozen=True)
class Added:
    """add_lines: the basket, then the lines for the drafts in order (an existing line for a duplicate need)."""

    basket: Basket
    lines: list[BasketLine]
    existing: list[int]  # line ids returned instead of a duplicate
    locked: bool = False  # the basket is ordered, nothing was added


@dataclass(frozen=True)
class Changed:
    basket: Basket
    line: BasketLine
    outcome: Outcome


def _now() -> str:
    return to_helsinki(datetime.now(UTC)).isoformat(timespec="seconds")


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")


def too_many_lines() -> HTTPException:
    return HTTPException(422, f"A basket holds at most {MAX_LINES} lines.")


# ---- the service ---------------------------------------------------------------------------------


class BasketService:
    """Baskets in SQLite, priced through StubState. Another buyer's basket is 'not found' (404), never its data."""

    def __init__(self, store: Store, stubs: StubState, settings: Settings) -> None:
        self.store = store
        self.stubs = stubs
        self.settings = settings  # read on every call: the as-of clock may change (tests, demos)

    @contextmanager
    def _tx(self, mode: str = "IMMEDIATE") -> Iterator[sqlite3.Connection]:
        with self.store.tx(mode) as c:
            c.row_factory = sqlite3.Row
            yield c

    # ---- pricing: the only place a line gets its numbers ----

    def price(self, d: LineDraft, chosen: str | None = None) -> Snapshot:
        """Price one line from its draft. `chosen` keeps the previous pick of a search need while it is an option."""
        pinned = d.product_id or (d.candidates[0] if len(d.candidates) == 1 else None)
        p = PRODUCTS.get(pinned) if pinned else None
        if d.amount is None or d.unit is None:
            return Snapshot(
                status="needs_amount",
                product_id=p.id if p else None,
                name_fi=p.name if p else None,
                message=NEEDS_AMOUNT,
            )
        if pinned and p is None:
            return Snapshot(status="unmatched", message=UNMATCHED)
        if p is not None and p.base_unit != d.unit:
            return Snapshot(
                status="needs_amount", product_id=p.id, name_fi=p.name, message=msg_unit([p.base_unit], p.name)
            )
        need_date = date.fromisoformat(d.need_date)
        options, refused, units = self._choices(d, d.amount, d.unit)
        if p is not None:  # pinned: that product, with the need's other options as alternatives
            offer = next((o for o in options if o.product_id == p.id), None)
            why: NotOffered | None = None
            if offer is None:
                offer, why = self.stubs.price_product(p.id, d.amount, d.unit, d.need_date, self.settings.as_of)
            alternatives = [o for o in options if o.product_id != p.id]
            if offer is not None:
                return self._priced(d, offer, alternatives)
            flags = why.flags if why else []
            cut = "CUTOFF_PASSED" in flags
            return Snapshot(
                status="cutoff_passed" if cut else "not_deliverable",
                product_id=p.id,
                name_fi=p.name,
                alternatives=alternatives,
                flags=flags,
                message=msg_cutoff(need_date) if cut else msg_not_deliverable(need_date, p.name),
            )
        if options and d.need is None:  # several matches from a sheet or a photo: the buyer chooses
            return Snapshot(status="needs_choice", alternatives=options, message=msg_choice(len(options)))
        if options:
            offer = next((o for o in options if o.product_id == chosen), options[0])
            return self._priced(d, offer, [o for o in options if o is not offer])
        if d.need is None and len(d.candidates) < 2:
            return Snapshot(status="unmatched", message=UNMATCHED)  # nothing to price
        flags = sorted({f for n in refused for f in n.flags if f in BLOCKING}, key=FLAG_ORDER.index)
        if "CUTOFF_PASSED" in flags:
            return Snapshot(status="cutoff_passed", flags=flags, message=msg_cutoff(need_date))
        if refused:
            return Snapshot(status="not_deliverable", flags=flags, message=msg_not_deliverable(need_date))
        if units and d.unit not in units:  # e.g. "voi 20 l": butter is sold per kilogram
            return Snapshot(status="needs_amount", message=msg_unit(units))
        return Snapshot(status="unmatched", message=UNMATCHED)

    def _choices(self, d: LineDraft, amount: float, unit: str) -> tuple[list[Offer], list[NotOffered], list[str]]:
        """Feasible offers (a search need's options, or the priced candidates), refusals, and the base units the
        matching products are sold in when none is sold in the line's unit."""
        if d.need is not None:
            req = d.offers_request()
            res = self.stubs.get_offers(req, self.settings.as_of)
            units = [] if res.counts["candidates"] else self._units(req)
            return res.options, res.not_offered, units
        if len(d.candidates) < 2:
            return [], [], []
        priced: list[Offer] = []
        refused: list[NotOffered] = []
        units: set[str] = set()
        for pid in d.candidates:
            p = PRODUCTS.get(pid)
            if p is None:
                continue
            if p.base_unit != unit:
                units.add(p.base_unit)
                continue
            o, why = self.stubs.price_product(pid, amount, unit, d.need_date, self.settings.as_of)
            if o is not None:
                priced.append(o)
            elif why is not None:
                refused.append(why)
        priced.sort(key=lambda o: rank(PRODUCTS[o.product_id]))
        return priced, refused, sorted(units)

    @staticmethod
    def _units(req: OffersRequest) -> list[str]:
        rows = [p for p in matches(req, heads_for(req)) if req.allow_variants or not p.variant]
        return sorted({p.base_unit for p in rows})

    @staticmethod
    def _priced(d: LineDraft, offer: Offer, alternatives: list[Offer]) -> Snapshot:
        p = PRODUCTS[offer.product_id]
        net = Decimal(offer.total_net)
        vat = vat_of(net, p.vat)  # VAT per line on the net total, rounded half-up (F-06)
        return Snapshot(
            status="priced",
            product_id=offer.product_id,
            name_fi=offer.name_fi,
            offer=offer,
            alternatives=alternatives,
            flags=offer.flags,
            message=msg_priced(offer),
            overshoot=num(Decimal(offer.content_total) - Decimal(str(d.amount))),
            vat_rate=str(p.vat),
            line_vat=money(vat),
            line_gross=money(net + vat),
        )

    # ---- reads ----

    def get(self, buyer: Buyer, basket_id: str) -> Basket:
        """The buyer's basket; 404 when it does not exist or belongs to someone else."""
        with self._tx("DEFERRED") as c:
            return self._load(c, buyer, basket_id)

    def current(self, buyer: Buyer) -> Basket | None:
        """The buyer's newest open basket, so a page reload finds it again (B-03)."""
        with self._tx("DEFERRED") as c:
            row = c.execute(
                "SELECT basket_id FROM basket WHERE buyer_id = ? AND status = 'open' ORDER BY rowid DESC LIMIT 1",
                (buyer.buyer_id,),
            ).fetchone()
            return self._load(c, buyer, row["basket_id"]) if row else None

    def is_stale(self, quote: Quote) -> bool:
        """True when the quote's basket changed after it was made, or is gone. Quotes without a basket never are."""
        if not quote.basket_id:
            return False
        with self._tx("DEFERRED") as c:
            row = c.execute(
                "SELECT version FROM basket WHERE basket_id = ? AND buyer_id = ?", (quote.basket_id, quote.buyer_id)
            ).fetchone()
        return row is None or row["version"] != quote.basket_version

    # ---- writes: each one is a single BEGIN IMMEDIATE transaction ----

    def create_basket(self, buyer: Buyer, conversation_id: str | None = None) -> Basket:
        with self._tx() as c:
            return self._load(c, buyer, self._insert(c, buyer, conversation_id))

    def add_lines(
        self,
        buyer: Buyer,
        basket_id_or_new: str,
        drafts: list[LineDraft],
        conversation_id: str | None = None,
        *,
        dedupe: bool = False,
    ) -> Added:
        """Price and add lines. 'new' starts a basket, except that a voice call reuses the open basket it started,
        so a retried tool call never makes a second one. With dedupe, a need identical to an active line's need
        returns that line instead of a duplicate."""
        now = _now()
        basket_id_or_new = basket_id_or_new.strip()  # an agent may pad the id
        with self._tx() as c:
            if basket_id_or_new.lower() == "new":
                row = None
                if conversation_id:
                    row = c.execute(
                        "SELECT basket_id FROM basket WHERE buyer_id = ? AND conversation_id = ? AND status = 'open'"
                        " ORDER BY rowid DESC LIMIT 1",
                        (buyer.buyer_id, conversation_id),
                    ).fetchone()
                basket_id = row["basket_id"] if row else self._insert(c, buyer, conversation_id)
            else:
                basket_id = basket_id_or_new
                if self._row(c, buyer, basket_id)["status"] == "ordered":
                    return Added(self._load(c, buyer, basket_id), [], [], locked=True)
            active = [(i, d) for i, d, _, on in self._lines(c, basket_id) if on]
            keys = {need_key(d): i for i, d in active} if dedupe else {}
            next_id = self._row(c, buyer, basket_id)["next_line_id"]
            out: list[int] = []
            existing: list[int] = []
            fresh: list[tuple[int, LineDraft]] = []
            for d in drafts:
                k = need_key(d) if dedupe else None
                if k is not None and k in keys:
                    out.append(keys[k])
                    existing.append(keys[k])
                    continue
                fresh.append((next_id, d))
                out.append(next_id)
                if k is not None:
                    keys[k] = next_id  # a second identical draft in this call finds this one
                next_id += 1
            if len(active) + len(fresh) > MAX_LINES:
                raise too_many_lines()
            for line_id, d in fresh:
                c.execute(
                    "INSERT INTO basket_line (basket_id, line_id, active, draft, priced, created_at, updated_at)"
                    " VALUES (?, ?, 1, ?, ?, ?, ?)",
                    (basket_id, line_id, d.model_dump_json(), self.price(d).model_dump_json(), now, now),
                )
            if fresh:
                self._bump(c, basket_id, now, next_line_id=next_id)
            basket = self._load(c, buyer, basket_id)
        by_id = {line.line_id: line for line in basket.lines}
        return Added(basket, [by_id[i] for i in out], existing)

    def update_line(self, buyer: Buyer, basket_id: str, line_id: int, patch: BasketLinePatch) -> Changed:
        """0 and "" keep a value. offer_id must be the current offer or one of the line's alternatives; choosing an
        alternative pins that product. Any change prices the line again."""
        with self._tx() as c:
            b, d, s, _ = self._target(c, buyer, basket_id, line_id)
            if b["status"] == "ordered":
                return self._changed(c, buyer, basket_id, line_id, "locked")
            update: dict[str, Any] = {}
            if patch.offer_id and patch.offer_id != (s.offer.offer_id if s.offer else ""):
                alt = next((o for o in s.alternatives if o.offer_id == patch.offer_id), None)
                if alt is None:
                    return self._changed(c, buyer, basket_id, line_id, "unknown_offer")
                update["product_id"] = alt.product_id
            if patch.amount:
                update["amount"] = patch.amount
            if patch.unit:
                update["unit"] = patch.unit
            if patch.need_date:
                update["need_date"] = patch.need_date
            return self._reprice(c, buyer, basket_id, line_id, d, s, update)

    def choose_product(self, buyer: Buyer, basket_id: str, line_id: int, product_id: str) -> Changed:
        """Pin a product on a line ('Replace line N' on an option card); the line is priced again."""
        with self._tx() as c:
            b, d, s, _ = self._target(c, buyer, basket_id, line_id)
            if b["status"] == "ordered":
                return self._changed(c, buyer, basket_id, line_id, "locked")
            return self._reprice(c, buyer, basket_id, line_id, d, s, {"product_id": product_id})

    def remove_line(self, buyer: Buyer, basket_id: str, line_id: int) -> Changed:
        """A soft delete: the line keeps its id and draft, so restore_line can bring it back."""
        with self._tx() as c:
            b, _, _, active = self._target(c, buyer, basket_id, line_id, removed_too=True)
            if b["status"] == "ordered":
                return self._changed(c, buyer, basket_id, line_id, "locked")
            if not active:
                return self._changed(c, buyer, basket_id, line_id, "unchanged")
            now = _now()
            c.execute(
                "UPDATE basket_line SET active = 0, updated_at = ? WHERE basket_id = ? AND line_id = ?",
                (now, basket_id, line_id),
            )
            self._bump(c, basket_id, now)
            return self._changed(c, buyer, basket_id, line_id, "removed")

    def restore_line(self, buyer: Buyer, basket_id: str, line_id: int) -> Changed:
        """Undo a removal. The line is priced again, so it comes back with current gateway numbers."""
        with self._tx() as c:
            b, d, s, active = self._target(c, buyer, basket_id, line_id, removed_too=True)
            if b["status"] == "ordered":
                return self._changed(c, buyer, basket_id, line_id, "locked")
            if active:
                return self._changed(c, buyer, basket_id, line_id, "unchanged")
            if self._active_count(c, basket_id) >= MAX_LINES:
                raise too_many_lines()
            now = _now()
            c.execute(
                "UPDATE basket_line SET active = 1, priced = ?, updated_at = ? WHERE basket_id = ? AND line_id = ?",
                (self.price(d, s.product_id).model_dump_json(), now, basket_id, line_id),
            )
            self._bump(c, basket_id, now)
            return self._changed(c, buyer, basket_id, line_id, "restored")

    def quote(self, buyer: Buyer, basket_id: str) -> BasketQuoteResponse:
        """quote_basket: one quote for the whole basket, or basket_incomplete with the lines to resolve first."""
        basket = self.get(buyer, basket_id)
        if basket.status == "ordered":
            q = self.stubs.get_quote(buyer, basket.quote_id) if basket.quote_id else None
            return BasketQuoteResponse(
                reason_code="basket_locked",
                basket_id=basket_id,
                quote_id=q.quote_id if q else None,
                quote=q,
                total_net=q.total_net if q else None,
                total_gross=q.total_gross if q else None,
                expires_at=q.expires_at if q else None,
                message_for_user=LOCKED,
            )
        waiting = open_lines(basket)
        if not basket.lines or waiting:
            return BasketQuoteResponse(
                status="incomplete",
                reason_code="basket_incomplete",
                basket_id=basket_id,
                open_lines=waiting,
                message_for_user=incomplete_text(basket),
                warnings=warnings_for(basket),
            )
        q = self.stubs.create_basket_quote(buyer, basket, self.settings.as_of)
        self.mark_quoted(buyer, basket_id, q.quote_id)
        return BasketQuoteResponse(
            status=q.status,
            basket_id=basket_id,
            quote_id=q.quote_id,
            quote=q,
            total_net=q.total_net,
            total_gross=q.total_gross,
            expires_at=q.expires_at,
            message_for_user=quote_text(q),
            warnings=["stub: quote is not signed yet (M6)", *invented_warnings(x.product_id for x in q.lines)],
        )

    def mark_quoted(self, buyer: Buyer, basket_id: str, quote_id: str) -> Basket:
        """Record the basket's latest quote. Not a change to the lines, so the version stays."""
        with self._tx() as c:
            self._row(c, buyer, basket_id)
            c.execute(
                "UPDATE basket SET quote_id = ?, updated_at = ? WHERE basket_id = ?", (quote_id, _now(), basket_id)
            )
            return self._load(c, buyer, basket_id)

    def mark_ordered(self, buyer: Buyer, basket_id: str) -> Basket:
        """The order exists: the basket becomes read-only (B-03). The version stays, so its quote stays valid."""
        with self._tx() as c:
            self._row(c, buyer, basket_id)
            c.execute(
                "UPDATE basket SET status = 'ordered', updated_at = ? WHERE basket_id = ? AND status != 'ordered'",
                (_now(), basket_id),
            )
            return self._load(c, buyer, basket_id)

    # ---- SQL helpers (always inside one transaction) ----

    @staticmethod
    def _insert(c: sqlite3.Connection, buyer: Buyer, conversation_id: str | None) -> str:
        now = _now()
        for _ in range(5):
            basket_id = "B-" + secrets.token_hex(5).upper()
            try:
                c.execute(
                    "INSERT INTO basket (basket_id, buyer_id, conversation_id, status, version, next_line_id,"
                    " quote_id, created_at, updated_at) VALUES (?, ?, ?, 'open', 1, 1, '', ?, ?)",
                    (basket_id, buyer.buyer_id, conversation_id, now, now),
                )
                return basket_id
            except sqlite3.IntegrityError:  # an id collision: draw again
                continue
        raise HTTPException(503, "could not create a basket")

    @staticmethod
    def _row(c: sqlite3.Connection, buyer: Buyer, basket_id: str) -> sqlite3.Row:
        row = c.execute(
            "SELECT * FROM basket WHERE basket_id = ? AND buyer_id = ?", (basket_id, buyer.buyer_id)
        ).fetchone()
        if row is None:
            raise not_found("basket")
        return row

    @staticmethod
    def _lines(c: sqlite3.Connection, basket_id: str) -> list[tuple[int, LineDraft, Snapshot, bool]]:
        rows = c.execute(
            "SELECT line_id, draft, priced, active FROM basket_line WHERE basket_id = ? ORDER BY line_id", (basket_id,)
        ).fetchall()
        return [
            (
                r["line_id"],
                LineDraft.model_validate_json(r["draft"]),
                Snapshot.model_validate_json(r["priced"]),
                bool(r["active"]),
            )
            for r in rows
        ]

    @staticmethod
    def _active_count(c: sqlite3.Connection, basket_id: str) -> int:
        return c.execute(
            "SELECT COUNT(*) FROM basket_line WHERE basket_id = ? AND active = 1", (basket_id,)
        ).fetchone()[0]

    def _target(
        self, c: sqlite3.Connection, buyer: Buyer, basket_id: str, line_id: int, *, removed_too: bool = False
    ) -> tuple[sqlite3.Row, LineDraft, Snapshot, bool]:
        b = self._row(c, buyer, basket_id)
        r = c.execute(
            "SELECT draft, priced, active FROM basket_line WHERE basket_id = ? AND line_id = ?", (basket_id, line_id)
        ).fetchone()
        if r is None or (not r["active"] and not removed_too):
            raise not_found("basket line")
        return (
            b,
            LineDraft.model_validate_json(r["draft"]),
            Snapshot.model_validate_json(r["priced"]),
            bool(r["active"]),
        )

    def _reprice(
        self,
        c: sqlite3.Connection,
        buyer: Buyer,
        basket_id: str,
        line_id: int,
        d: LineDraft,
        s: Snapshot,
        update: dict[str, Any],
    ) -> Changed:
        new = d.model_copy(update=update)
        if new == d:
            return self._changed(c, buyer, basket_id, line_id, "unchanged")
        now = _now()
        c.execute(
            "UPDATE basket_line SET draft = ?, priced = ?, updated_at = ? WHERE basket_id = ? AND line_id = ?",
            (new.model_dump_json(), self.price(new, s.product_id).model_dump_json(), now, basket_id, line_id),
        )
        self._bump(c, basket_id, now)
        return self._changed(c, buyer, basket_id, line_id, "changed")

    @staticmethod
    def _bump(c: sqlite3.Connection, basket_id: str, now: str, next_line_id: int | None = None) -> None:
        """Every change to the lines bumps the version, which makes an earlier quote stale."""
        if next_line_id is None:
            c.execute("UPDATE basket SET version = version + 1, updated_at = ? WHERE basket_id = ?", (now, basket_id))
        else:
            c.execute(
                "UPDATE basket SET version = version + 1, next_line_id = ?, updated_at = ? WHERE basket_id = ?",
                (next_line_id, now, basket_id),
            )

    def _changed(self, c: sqlite3.Connection, buyer: Buyer, basket_id: str, line_id: int, outcome: Outcome) -> Changed:
        basket = self._load(c, buyer, basket_id)
        line = next((x for x in basket.lines if x.line_id == line_id), None)
        if line is None:  # a removed line is not in the basket: build it from its row
            _, d, s, _ = self._target(c, buyer, basket_id, line_id, removed_too=True)
            line = to_line(line_id, d, s)
        return Changed(basket, line, outcome)

    def _load(self, c: sqlite3.Connection, buyer: Buyer, basket_id: str) -> Basket:
        b = self._row(c, buyer, basket_id)
        lines = [to_line(i, d, s) for i, d, s, on in self._lines(c, basket_id) if on]
        counts = dict.fromkeys(STATUSES, 0)
        for line in lines:
            counts[line.status] += 1
        priced = [line for line in lines if line.status == "priced" and line.offer is not None]
        quote = self.stubs.quotes.get(b["quote_id"]) if b["quote_id"] else None
        return Basket(
            basket_id=b["basket_id"],
            buyer_id=b["buyer_id"],
            status=b["status"],
            version=b["version"],
            lines=lines,
            counts=counts,
            total_net=money(sum((Decimal(x.offer.total_net) for x in priced if x.offer), Decimal(0))),
            total_vat=money(sum((Decimal(x.line_vat or 0) for x in priced), Decimal(0))),
            total_gross=money(sum((Decimal(x.line_gross or 0) for x in priced), Decimal(0))),
            quote_id=b["quote_id"],
            quote_stale=bool(b["quote_id"]) and (quote is None or quote.basket_version != b["version"]),
            created_at=b["created_at"],
            updated_at=b["updated_at"],
        )


# ---- responses -----------------------------------------------------------------------------------

OPEN_TEXT: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {  # status: ((fi one, fi many), (en one, en many))
    "needs_choice": (
        ("Rivi {} odottaa valintaasi.", "Rivit {} odottavat valintaasi."),
        ("Line {} needs your choice.", "Lines {} need your choice."),
    ),
    "needs_amount": (
        ("Rivi {} tarvitsee määrän.", "Rivit {} tarvitsevat määrän."),
        ("Line {} needs an amount.", "Lines {} need an amount."),
    ),
    "unmatched": (
        ("Riviä {} ei löytynyt luettelosta.", "Rivejä {} ei löytynyt luettelosta."),
        ("Line {} was not found in the catalogue.", "Lines {} were not found in the catalogue."),
    ),
    "not_deliverable": (
        ("Riviä {} ei voi toimittaa.", "Rivejä {} ei voi toimittaa."),
        ("Line {} cannot be delivered.", "Lines {} cannot be delivered."),
    ),
    "cutoff_passed": (
        ("Rivin {} tilausaika on mennyt.", "Rivien {} tilausaika on mennyt."),
        ("The cut-off for line {} has passed.", "The cut-off for lines {} has passed."),
    ),
}


def open_lines(basket: Basket) -> list[int]:
    """Lines that must be resolved before a quote: every active line that is not priced."""
    return [line.line_id for line in basket.lines if line.status != "priced"]


def open_text(basket: Basket) -> tuple[list[str], list[str]]:
    fi_parts, en_parts = [], []
    for status, ((fi1, fin), (en1, enn)) in OPEN_TEXT.items():
        ids = [line.line_id for line in basket.lines if line.status == status]
        if ids:
            fi_parts.append((fi1 if len(ids) == 1 else fin).format(ids_fi(ids)))
            en_parts.append((en1 if len(ids) == 1 else enn).format(ids_en(ids)))
    return fi_parts, en_parts


def summary(basket: Basket, *, ordered_note: bool = True) -> Msg:
    """A short summary built from gateway numbers: lines, the total of priced lines, what is open."""
    n = len(basket.lines)
    if n == 0:
        fi_parts, en_parts = ["Kori on tyhjä."], ["The basket is empty."]
    else:
        fi_parts = [f"Korissa {'1 rivi' if n == 1 else f'{n} riviä'}, yhteensä {fi(basket.total_net)} € alv 0 %."]
        en_parts = [f"The basket has {'1 line' if n == 1 else f'{n} lines'}, EUR {basket.total_net} excl. VAT."]
    more_fi, more_en = open_text(basket)
    fi_parts += more_fi
    en_parts += more_en
    if basket.status == "ordered" and ordered_note:
        fi_parts.append("Kori on tilattu, eikä sitä voi enää muuttaa.")
        en_parts.append("The basket is ordered and can no longer change.")
    elif basket.status == "open" and basket.quote_stale:
        fi_parts.append("Tarjous on vanhentunut, koska kori muuttui: pyydä uusi tarjous.")
        en_parts.append("The quote is out of date because the basket changed: make a new quote.")
    return Msg(fi=" ".join(fi_parts), en=" ".join(en_parts))


def incomplete_text(basket: Basket) -> Msg:
    if not basket.lines:
        return Msg(
            fi="Kori on tyhjä, joten tarjottavaa ei ole. Lisää ensin tuotteita.",
            en="The basket is empty, so there is nothing to quote. Add products first.",
        )
    more_fi, more_en = open_text(basket)
    one = len(open_lines(basket)) == 1
    return Msg(
        fi=f"Tarjousta ei voi vielä tehdä. {' '.join(more_fi)} "
        + ("Ratkaise se ensin tai poista se." if one else "Ratkaise ne ensin tai poista ne."),
        en=f"No quote yet. {' '.join(more_en)} "
        + ("Resolve it first or remove it." if one else "Resolve them first or remove them."),
    )


def quote_text(q: Quote) -> Msg:
    n, until = len(q.lines), datetime.fromisoformat(q.expires_at)
    return Msg(
        fi=f"Tarjous {q.quote_id}: {'1 rivi' if n == 1 else f'{n} riviä'}, {fi(q.total_net)} € alv 0 % "
        f"({fi(q.total_gross)} € sis. alv). Hinta on kiinteä {clock_fi(until)} asti. Vahvista tilaus näytöltä.",
        en=f"Quote {q.quote_id}: {'1 line' if n == 1 else f'{n} lines'}, EUR {q.total_net} excl. VAT "
        f"(EUR {q.total_gross} incl. VAT). The price is fixed until {clock_en(until)}. Please confirm on screen.",
    )


def line_short(line: BasketLine) -> Msg:
    if line.status == "priced" and line.offer is not None:
        o = line.offer
        return Msg(
            fi=f"{o.qty} × {o.api_unit} {quoted(o.name_fi)}, {fi(o.total_net)} € alv 0 %.",
            en=f"{o.qty} × {o.api_unit} {quoted(o.name_fi)}, EUR {o.total_net} excl. VAT.",
        )
    return line.message


def note(outcome: Outcome, line: BasketLine) -> Msg:
    i, short = line.line_id, line_short(line)
    match outcome:
        case "added":
            return Msg(fi=f"Lisäsin rivin {i}: {short.fi}", en=f"Added line {i}: {short.en}")
        case "duplicate":
            return Msg(
                fi=f"Tämä tarve on jo rivillä {i}, joten en lisännyt sitä uudelleen.",
                en=f"This need is already line {i}, so I did not add it again.",
            )
        case "changed":
            return Msg(fi=f"Päivitin rivin {i}: {short.fi}", en=f"Updated line {i}: {short.en}")
        case "unchanged":
            return Msg(fi=f"Rivillä {i} ei ollut muutettavaa.", en=f"Nothing to change on line {i}.")
        case "unknown_offer":
            return Msg(
                fi=f"Se tarjous ei ole rivin {i} vaihtoehto, joten rivi ei muuttunut.",
                en=f"That offer is not one of line {i}'s options, so the line is unchanged.",
            )
        case "removed":
            return Msg(fi=f"Poistin rivin {i}. Sen voi palauttaa.", en=f"Removed line {i}. It can be restored.")
        case "restored":
            return Msg(fi=f"Palautin rivin {i}: {short.fi}", en=f"Restored line {i}: {short.en}")
        case "locked":
            return LOCKED
    return line.message


REASON: dict[Outcome, Any] = {"locked": "basket_locked", "unknown_offer": "unknown_id"}


def warnings_for(basket: Basket, *lines: BasketLine | None) -> list[str]:
    shown = [*basket.lines, *(x for x in lines if x is not None)]
    ids = [i for x in shown for i in (x.product_id, *(o.product_id for o in (x.offer, *x.alternatives) if o))]
    return invented_warnings(ids)


def respond(basket: Basket, line: BasketLine | None = None, outcome: Outcome | None = None) -> BasketResponse:
    """A BasketResponse: what this call did, then the basket summary, in both languages."""
    if outcome == "locked":
        head: Msg | None = LOCKED
    else:
        head = note(outcome, line) if outcome and line else None
    s = summary(basket, ordered_note=outcome != "locked")
    return BasketResponse(
        reason_code=REASON.get(outcome) if outcome else None,
        basket_id=basket.basket_id,
        basket=basket,
        line=line,
        message_for_user=s if head is None else Msg(fi=f"{head.fi} {s.fi}", en=f"{head.en} {s.en}"),
        warnings=warnings_for(basket, line),
    )


# ---- the FastAPI dependency (main.py stays untouched) ---------------------------------------------

_create = threading.Lock()


def service(app: Any, settings: Settings) -> BasketService:
    """The app's basket service, created on first use from app.state.store and app.state.stubs."""
    with _create:
        svc = getattr(app.state, "baskets", None)
        if svc is None:
            svc = BasketService(app.state.store, app.state.stubs, settings)
            app.state.baskets = svc
    return svc


def basket_service(request: Request, settings: SettingsDep) -> BasketService:
    return service(request.app, settings)


BasketsDep = Annotated[BasketService, Depends(basket_service)]
