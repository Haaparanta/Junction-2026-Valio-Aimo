"""Orders and approvals (PLAN M8.1-8.3, M9.1, M9.3, M9.5), in memory next to the stub quotes.

* State machine with the UCP checkout statuses: an order is made `incomplete` from an unexpired, confirmed quote, moves
  through `ready_for_complete` to `completed`, or to `requires_escalation` (an approval, or a re-check that failed), or
  to `canceled`. completed and canceled are final.
* Policy: policy.evaluate under the caller's own mandate. allow -> completed; require_approval -> requires_escalation
  with an approval (decide_by = the earliest order-by time minus 1 hour); deny -> canceled.
* Pre-order re-check (M8.3): price and availability are read again from the stubs just before an order is completed
  or sent for approval, and again when it is approved. Any drift moves it to requires_escalation with price_changed;
  the quote is dropped, so create_quote or quote_basket makes a new one that needs a new confirmation.
* Idempotency (M8.2): one order per quote version. A key (the Idempotency-Key header, or one derived from the voice
  conversation or web session and the quote) with the same payload answers the same order; with another, HTTP 409.
* Approvals: only an approver of the same organisation decides, never the order's own buyer; any change to the quote
  voids the approval; a decision after decide_by (as of the demo clock) expires it. Deciding twice answers the first
  decision.

Ownership is checked here: an order belongs to the buyer who placed it; an approver of the same org may read it.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from .contract import (
    Approval,
    ApprovalLine,
    ApprovalListResponse,
    ApprovalResponse,
    ApprovalSummary,
    Msg,
    Offer,
    Order,
    OrderResponse,
    Quote,
    ReasonCode,
    TradeStatus,
)
from .fmt import at_en, at_fi, day_en, day_fi, fi, helsinki_at, instant, money, quoted, to_helsinki
from .identity import Buyer
from .mandates import for_buyer
from .policy import Decision, LineFacts, OpenLine, PolicyContext, Reason, evaluate
from .stubs import PRODUCTS, StubState, assess, order_by, sha

DECIDE_BUFFER = timedelta(hours=1)  # decide_by = the earliest order-by time minus this (G-07)
SUBSTITUTE_SET = "OS-SUBST"  # the offer set find_substitutes makes its offers in
TRANSITIONS: dict[TradeStatus, set[TradeStatus]] = {
    "incomplete": {"ready_for_complete", "requires_escalation", "canceled"},
    "ready_for_complete": {"completed", "requires_escalation", "canceled"},
    "requires_escalation": {"ready_for_complete", "canceled"},
    "completed": set(),
    "canceled": set(),
}
OPEN = {"ready_for_complete", "completed"}  # with a pending approval, requires_escalation counts too


class IdempotencyConflict(Exception):
    """The idempotency key was used before with a different payload (HTTP 409)."""


class IllegalTransition(Exception):
    pass


@dataclass
class OrderMeta:
    """What the gateway keeps about an order beyond the contract model."""

    buyer: Buyer
    quote: Quote  # the quote as it was ordered; the stub quote itself may be dropped after a re-check
    quote_sha256: str
    seq: int
    approval_seq: int = 0
    keys: set[str] = field(default_factory=set)
    reasons: list[Reason] = field(default_factory=list)  # the policy's or the re-check's, with their Finnish text


def quote_sha(q: Quote) -> str:
    """The hash an approval records: the quote's content, without its confirmation state."""
    return sha(q.model_dump_json(exclude={"status", "confirmed", "confirmed_at"}))


def transition(o: Order, to: TradeStatus, **update) -> Order:
    if to not in TRANSITIONS[o.status]:
        raise IllegalTransition(f"{o.status} -> {to}")
    return o.model_copy(update={"status": to, **update})


# ---- the policy context --------------------------------------------------------------------------


def single_quote_offer(state: StubState, buyer: Buyer, quote: Quote) -> Offer | None:
    """The offer create_quote made this quote from (quote ids are a hash of the buyer and the offer id)."""
    for oid, o in list(state.offers.items()):
        if o.product_id == quote.lines[0].product_id and "Q-" + sha(f"{buyer.buyer_id}|{oid}")[:10].upper() == (
            quote.quote_id
        ):
            return o
    return None


def line_facts(
    state: StubState, buyer: Buyer, quote: Quote, offers_by_line: dict[int, Offer | None] | None = None
) -> list[LineFacts]:
    """What the policy needs to know about each quote line: its product, how it was offered and for what need."""
    if offers_by_line is None:
        o = single_quote_offer(state, buyer, quote) if not quote.basket_id and len(quote.lines) == 1 else None
        offers_by_line = {quote.lines[0].line_id: o} if o else {}
    previous = previous_prices(state, buyer)
    facts = []
    for x in quote.lines:
        p = PRODUCTS.get(x.product_id)
        offer = offers_by_line.get(x.line_id)
        set_id = offer.offer_id.rsplit(":", 1)[0] if offer else ""
        need = state.offer_request(set_id) if set_id else None
        if offer is not None:
            flags = tuple(offer.flags)
        elif p is not None and p.sales_unit != p.api_unit:
            flags = ("UNIT_MISMATCH",)
        else:
            flags = ()
        facts.append(
            LineFacts(
                line_id=x.line_id,
                product_id=x.product_id,
                name_fi=x.name_fi,
                qty=x.qty,
                unit_price_net=Decimal(x.unit_price_net),
                line_net=Decimal(x.line_net),
                delivery_date=date.fromisoformat(x.delivery_date),
                category=p.category if p else "",
                temperature=p.temperature if p else "unknown",
                allergens=p.allergens if p else (),
                allergen_data=p.allergen_data if p else "unknown",
                claims=p.claims if p else (),
                flags=flags,
                substituted=set_id == SUBSTITUTE_SET,
                # X-17 NET_ABOVE_LIST: the stub rows carry no list price yet, so this stays None until M3 brings
                # listPrice; policy.evaluate already applies the trigger when a list price is known.
                list_price=getattr(p, "list_price", None),
                previous_price=previous.get(x.product_id),
                diet_known=need is not None,
                must_claims=tuple(need.must_claims) if need else (),
                must_not_allergens=tuple(need.must_not_allergens) if need else (),
            )
        )
    return facts


def is_open(state: StubState, o: Order) -> bool:
    if o.status in OPEN:
        return True
    a = state.approvals.get(o.approval_id or "")
    return o.status == "requires_escalation" and a is not None and a.status == "requires_escalation"


def open_lines(state: StubState, buyer: Buyer, exclude: str = "") -> list[OpenLine]:
    """The lines of the buyer's other open orders: the requisition and the weekly budget count them (R-07)."""
    out = []
    for oid, o in state.orders.items():
        meta = state.order_meta.get(oid)
        if oid == exclude or meta is None or meta.buyer.buyer_id != buyer.buyer_id or not is_open(state, o):
            continue
        out += [OpenLine(oid, date.fromisoformat(x.delivery_date), Decimal(x.line_net)) for x in meta.quote.lines]
    return out


def previous_prices(state: StubState, buyer: Buyer) -> dict[str, Decimal]:
    """The unit price on the buyer's latest open order of each product (PRICE_JUMP compares against it)."""
    prices: dict[str, Decimal] = {}
    for oid, meta in sorted(state.order_meta.items(), key=lambda kv: kv[1].seq):
        o = state.orders.get(oid)
        if meta.buyer.buyer_id == buyer.buyer_id and o is not None and is_open(state, o):
            prices.update({x.product_id: Decimal(x.unit_price_net) for x in meta.quote.lines})
    return prices


# ---- the pre-order re-check ----------------------------------------------------------------------


def recheck(quote: Quote, now: datetime) -> list[Reason]:
    """Price and availability read again from the stubs (M8.3). Empty when the quote still holds."""
    drift = []
    for x in quote.lines:
        p = PRODUCTS.get(x.product_id)
        if p is None:
            drift.append(Reason("NOT_DELIVERABLE", f"line {x.line_id} ({x.product_id}) is no longer sold", "poistunut"))
            continue
        if p.price != Decimal(x.unit_price_net):
            drift.append(
                Reason(
                    "PRICE_CHANGED",
                    f"line {x.line_id} ({x.product_id}) EUR {x.unit_price_net} is now EUR {money(p.price)}",
                    f"rivin {x.line_id} hinta {fi(x.unit_price_net)} € on nyt {fi(money(p.price))} €",
                )
            )
        _, _, blocking = assess(p, p.content * x.qty, date.fromisoformat(x.delivery_date), now)
        drift += [
            Reason(flag, f"line {x.line_id} ({x.product_id}) for {x.delivery_date}", f"rivi {x.line_id}")
            for flag in blocking
        ]
    return drift


def decide_by(quote: Quote) -> datetime:
    times = []
    for x in quote.lines:
        p = PRODUCTS.get(x.product_id)
        d = date.fromisoformat(x.delivery_date)
        times.append((order_by(p, d) if p else None) or helsinki_at(d - timedelta(days=1), "17:00"))
    return to_helsinki(min(times) - DECIDE_BUFFER)


# ---- messages ------------------------------------------------------------------------------------


def _join(parts: list[str]) -> str:
    return "; ".join(parts)


def order_message(state: StubState, o: Order) -> Msg:
    a = state.approvals.get(o.approval_id or "")
    meta = state.order_meta.get(o.order_id)
    total_fi, total_en = fi(o.total_net), o.total_net
    if o.status == "completed":
        d = date.fromisoformat(o.delivery_date)
        return Msg(
            fi=f"Tilaus {o.order_id} on vahvistettu: {total_fi} € alv 0 %, toimitus {day_fi(d)}.",
            en=f"Order {o.order_id} is confirmed: EUR {total_en} excl. VAT, delivery {day_en(d)}.",
        )
    if o.status == "requires_escalation" and a is not None and a.status == "requires_escalation":
        by = instant(a.decide_by)
        reasons_fi = _join([r.fi for r in meta.reasons]) if meta and meta.reasons else _join(a.reasons)
        reasons_en = _join([r.split(": ", 1)[-1] for r in a.reasons])
        return Msg(
            fi=f"Tilaus {total_fi} € lähti esihenkilösi hyväksyttäväksi ({reasons_fi}). "
            f"Hyväksyntä tarvitaan {at_fi(by)} mennessä.",
            en=f"The order of EUR {total_en} went to your manager for approval ({reasons_en}). "
            f"It needs approval by {at_en(by)}.",
        )
    if o.status == "requires_escalation":  # the re-check failed, or a change to the quote voided the approval
        return Msg(
            fi="Hinta tai saatavuus muuttui tarjouksen jälkeen, joten tilausta ei tehty. Tehdään uusi tarjous.",
            en="The price or availability changed after the quote, so the order was not placed. "
            "Let's make a new quote.",
        )
    if o.reason_code == "approval_rejected":
        note_fi = f" Kommentti: {quoted(a.comment)}." if a and a.comment else ""
        note_en = f" Comment: {quoted(a.comment)}." if a and a.comment else ""
        return Msg(
            fi=f"Esihenkilö hylkäsi tilauksen {o.order_id}, joten se on peruttu.{note_fi}",
            en=f"Your manager rejected order {o.order_id}, so it is canceled.{note_en}",
        )
    if o.reason_code == "quote_expired":
        return Msg(
            fi=f"Tilaus {o.order_id} peruttiin, koska hyväksyntää ei saatu ajoissa. Tehdään uusi tarjous.",
            en=f"Order {o.order_id} was canceled because it was not approved in time. Let's make a new quote.",
        )
    if o.reason_code == "policy_denied":
        reasons_fi = _join([r.fi for r in meta.reasons]) if meta and meta.reasons else _join(o.reasons)
        return Msg(
            fi=f"Tilausta ei voi tehdä: {reasons_fi}.",
            en=f"This order cannot be placed: {_join([r.split(': ', 1)[-1] for r in o.reasons])}.",
        )
    return Msg(fi=f"Tilaus {o.order_id} on peruttu.", en=f"Order {o.order_id} is canceled.")


def order_response(state: StubState, o: Order) -> OrderResponse:
    warnings = ["stub: orders are kept in memory and not sent to Valio Aimo (A-17)"]
    return OrderResponse(
        status=o.status,
        reason_code=o.reason_code,
        order_id=o.order_id,
        order=o,
        approval_id=o.approval_id,
        approval_url=o.approval_url,
        total_net=o.total_net,
        message_for_user=order_message(state, o),
        warnings=warnings,
    )


def approval_message(a: Approval, o: Order | None) -> Msg:
    by = instant(a.decide_by)
    oid = a.order_id
    match a.outcome:
        case None:
            return Msg(
                fi=f"Odottaa esihenkilön hyväksyntää {at_fi(by)} mennessä.",
                en=f"Waiting for the manager's approval by {at_en(by)}.",
            )
        case "approved":
            return Msg(fi=f"Hyväksytty. Tilaus {oid} on vahvistettu.", en=f"Approved. Order {oid} is confirmed.")
        case "rejected":
            return Msg(fi=f"Hylätty. Tilaus {oid} on peruttu.", en=f"Rejected. Order {oid} is canceled.")
        case "expired":
            return Msg(
                fi=f"Hyväksynnän määräaika {at_fi(by)} meni umpeen, joten tilaus {oid} peruttiin.",
                en=f"The approval deadline {at_en(by)} passed, so order {oid} was canceled.",
            )
        case "voided":
            return Msg(
                fi="Hinta tai saatavuus muuttui tarjouksen jälkeen, joten hyväksyntä mitätöitiin. "
                "Ostajan pitää pyytää uusi tarjous.",
                en="The price or availability changed after the quote, so the approval is void. "
                "The buyer needs a new quote.",
            )
        case _:
            return Msg(fi=f"Ostaja perui tilauksen {oid}.", en=f"The buyer canceled order {oid}.")


def approval_response(state: StubState, a: Approval) -> ApprovalResponse:
    o = state.orders.get(a.order_id)
    return ApprovalResponse(
        status=a.status,
        reason_code=a.reason_code,
        approval_id=a.approval_id,
        approval=a,
        order=o,
        message_for_user=approval_message(a, o),
        warnings=["stub: approvals are kept in memory"],
    )


# ---- place, read and cancel orders ---------------------------------------------------------------


def _incomplete(reason: ReasonCode, f: str, e: str) -> OrderResponse:
    return OrderResponse(status="incomplete", reason_code=reason, message_for_user=Msg(fi=f, en=e))


def _escalate_drift(state: StubState, o: Order, drift: list[Reason], quote_id: str) -> Order:
    """The quote no longer holds: requires_escalation with price_changed, and the stub quote is dropped so the next
    create_quote or quote_basket prices it again (M6.4, M8.3)."""
    state.quotes.pop(quote_id, None)
    update = {"reason_code": "price_changed", "reasons": [str(r) for r in drift]}
    if o.status == "requires_escalation":  # an approved order whose quote no longer holds stays where it is
        return o.model_copy(update=update)
    return transition(o, "requires_escalation", **update)


def place_order(
    state: StubState,
    buyer: Buyer,
    quote_id: str,
    key: str | None,
    scope: str,
    payload: str,
    as_of: str,
    offers_by_line: dict[int, Offer | None] | None = None,
) -> OrderResponse:
    """Turn the buyer's confirmed quote into an order. `key` is the caller's Idempotency-Key (None: derived from
    `scope` and the quote); `payload` is the request body as sent. Raises IdempotencyConflict for a reused key."""
    now = instant(as_of)
    q = state.get_quote(buyer, quote_id)
    if q is None:
        return _incomplete(
            "not_found",
            "Tarjousta ei löytynyt. Pyydä uusi tarjous.",
            "I could not find that quote. Let's make a new one.",
        )
    qsha = quote_sha(q)
    idem = f"{buyer.buyer_id}|key:{key}" if key else f"{scope}|{quote_id}|{qsha}"
    fingerprint = sha(f"{payload}|{qsha}")
    order_id = "O-" + sha(f"{buyer.buyer_id}|{quote_id}|{qsha}")[:10].upper()
    with state.lock:
        seen = state.idempotency.get(idem)
        if seen is not None and seen[0] != fingerprint:
            raise IdempotencyConflict(idem)
        existing = state.orders.get(seen[1] if seen else order_id)
        if existing is not None:
            state.idempotency.setdefault(idem, (fingerprint, existing.order_id))
            return order_response(state, existing)
    if not q.confirmed:
        return _incomplete(
            "confirmation_required",
            "Tilaus pitää ensin vahvistaa näytöltä.",
            "The buyer must confirm the quote on screen first.",
        )
    if instant(q.expires_at) <= now:
        return _incomplete(
            "quote_expired",
            "Tarjouksen hinta ei ole enää voimassa. Tehdään uusi tarjous.",
            "The quote's fixed price has expired. Let's make a new quote.",
        )

    facts = line_facts(state, buyer, q, offers_by_line)
    with state.lock:
        if order_id in state.orders:  # a concurrent call made it meanwhile
            return order_response(state, state.orders[order_id])
        decision: Decision = evaluate(for_buyer(buyer), q, PolicyContext(facts, open_lines(state, buyer)))
        state.seq += 1
        o = Order(
            order_id=order_id,
            quote_id=quote_id,
            status="incomplete",
            total_net=q.total_net,
            total_gross=q.total_gross,
            delivery_date=q.delivery_date,
            created_at=now.isoformat(),
        )
        meta = OrderMeta(buyer, q, qsha, state.seq, keys={idem}, reasons=decision.reasons)
        if decision.outcome == "deny":
            o = transition(
                o,
                "canceled",
                reason_code=decision.reason_code,
                reasons=decision.reason_strings,
                canceled_at=now.isoformat(),
            )
        elif drift := recheck(q, now):
            meta.reasons = drift
            o = _escalate_drift(state, o, drift, quote_id)
        elif decision.outcome == "allow":
            o = transition(o, "ready_for_complete")
            o = transition(o, "completed", completed_at=now.isoformat())
        else:
            approval_id = "A-" + order_id[2:]
            o = transition(
                o,
                "requires_escalation",
                reason_code=decision.reason_code,
                reasons=decision.reason_strings,
                approval_id=approval_id,
                approval_url=f"/approvals/{approval_id}",
            )
            meta.approval_seq = state.seq
            state.approvals[approval_id] = Approval(
                approval_id=approval_id,
                status="requires_escalation",
                order_id=order_id,
                quote_id=quote_id,
                reasons=decision.reason_strings,
                decide_by=decide_by(q).isoformat(),
                approver_role="approver",
                buyer_name=buyer.display_name,
                org_id=buyer.org_id,
                quote_sha256=qsha,
                created_at=now.isoformat(),
            )
        state.orders[order_id] = o
        state.order_meta[order_id] = meta
        state.idempotency[idem] = (fingerprint, order_id)
        return order_response(state, o)


def _may_read(buyer: Buyer, meta: OrderMeta | None) -> bool:
    if meta is None:
        return False
    owner = meta.buyer
    return owner.buyer_id == buyer.buyer_id or (buyer.role == "approver" and buyer.org_id == owner.org_id)


def _expire_if_due(state: StubState, approval_id: str, now: datetime | None) -> None:
    """An unanswered approval past decide_by (as of the demo clock) expires, and its order is canceled. Under lock."""
    a = state.approvals.get(approval_id)
    if now is None or a is None or a.status != "requires_escalation" or now < instant(a.decide_by):
        return
    state.approvals[approval_id] = a.model_copy(
        update={"status": "canceled", "outcome": "expired", "reason_code": "quote_expired"}
    )
    o = state.orders.get(a.order_id)
    if o is not None and o.status == "requires_escalation":
        state.orders[o.order_id] = transition(o, "canceled", reason_code="quote_expired", canceled_at=now.isoformat())


def get_order(state: StubState, buyer: Buyer, order_id: str, as_of: str | None = None) -> OrderResponse | None:
    with state.lock:
        o = state.orders.get(order_id)
        if o is None or not _may_read(buyer, state.order_meta.get(order_id)):
            return None
        if o.approval_id:
            _expire_if_due(state, o.approval_id, instant(as_of) if as_of else None)
        return order_response(state, state.orders[order_id])


def cancel_order(state: StubState, buyer: Buyer, order_id: str, as_of: str) -> OrderResponse | None:
    """The buyer cancels an order that is not completed; a pending approval is withdrawn with it."""
    now = instant(as_of)
    with state.lock:
        o = state.orders.get(order_id)
        meta = state.order_meta.get(order_id)
        if o is None or meta is None or meta.buyer.buyer_id != buyer.buyer_id:
            return None
        if o.approval_id:
            _expire_if_due(state, o.approval_id, now)
            o = state.orders[order_id]
        if o.status not in ("completed", "canceled"):
            o = transition(o, "canceled", reason_code=None, canceled_at=now.isoformat())
            state.orders[order_id] = o
            a = state.approvals.get(o.approval_id or "")
            if a is not None and a.status == "requires_escalation":
                state.approvals[a.approval_id] = a.model_copy(update={"status": "canceled", "outcome": "withdrawn"})
        return order_response(state, o)


# ---- approvals -----------------------------------------------------------------------------------


def _approval_owner(state: StubState, a: Approval) -> Buyer | None:
    meta = state.order_meta.get(a.order_id)
    return meta.buyer if meta else None


def get_approval(state: StubState, buyer: Buyer, approval_id: str, as_of: str | None = None) -> ApprovalResponse | None:
    """The order's buyer or an approver of the same org may read an approval."""
    with state.lock:
        a = state.approvals.get(approval_id)
        if a is None or not _may_read(buyer, state.order_meta.get(a.order_id)):
            return None
        _expire_if_due(state, approval_id, instant(as_of) if as_of else None)
        return approval_response(state, state.approvals[approval_id])


def list_approvals(state: StubState, approver: Buyer, as_of: str) -> ApprovalListResponse:
    """The approver's own org: pending first, newest first."""
    now = instant(as_of)
    with state.lock:
        rows = []
        for aid in list(state.approvals):
            _expire_if_due(state, aid, now)
            a = state.approvals[aid]
            meta = state.order_meta.get(a.order_id)
            if meta is None or a.org_id != approver.org_id:
                continue
            q = meta.quote
            rows.append(
                (
                    a.status != "requires_escalation",
                    -meta.approval_seq,
                    ApprovalSummary(
                        approval_id=a.approval_id,
                        status=a.status,
                        order_id=a.order_id,
                        quote_id=a.quote_id,
                        buyer_name=a.buyer_name,
                        total_net=q.total_net,
                        total_gross=q.total_gross,
                        delivery_date=q.delivery_date,
                        decide_by=a.decide_by,
                        reasons=a.reasons,
                        lines=[
                            ApprovalLine(name_fi=x.name_fi, qty=x.qty, api_unit=x.api_unit, line_net=x.line_net)
                            for x in q.lines
                        ],
                    ),
                )
            )
    rows.sort(key=lambda r: (r[0], r[1]))
    pending = sum(1 for r in rows if not r[0])
    return ApprovalListResponse(
        approvals=[r[2] for r in rows],
        message_for_user=Msg(
            fi=f"{pending} hyväksyntää odottaa." if pending != 1 else "1 hyväksyntä odottaa.",
            en=f"{pending} approval{'s' if pending != 1 else ''} waiting.",
        ),
        warnings=["stub: approvals are kept in memory"],
    )


class NotYours(Exception):
    """The approver may not decide this approval (another org, or their own order): HTTP 403."""


def decide(
    state: StubState, approver: Buyer, approval_id: str, decision: str, comment: str, as_of: str
) -> ApprovalResponse | None:
    """Approve or reject, under an approver's console session. None: no such approval in the approver's org."""
    now = instant(as_of)
    with state.lock:
        a = state.approvals.get(approval_id)
        owner = _approval_owner(state, a) if a else None
        if a is None or owner is None or a.org_id != approver.org_id:
            return None
        if owner.buyer_id == approver.buyer_id:
            raise NotYours(approval_id)
        _expire_if_due(state, approval_id, now)
        a = state.approvals[approval_id]
        if a.status != "requires_escalation":  # decided (or expired) already: the first answer stands
            return approval_response(state, a)
        o = state.orders[a.order_id]
        meta = state.order_meta[a.order_id]
        stamp = {"decided_by": approver.display_name, "decided_at": now.isoformat(), "comment": comment}
        if decision == "reject":
            a = a.model_copy(
                update={"status": "canceled", "outcome": "rejected", "reason_code": "approval_rejected", **stamp}
            )
            o = transition(o, "canceled", reason_code="approval_rejected", canceled_at=now.isoformat())
        else:
            current = state.quotes.get(a.quote_id)
            drift = recheck(meta.quote, now)
            if current is None or quote_sha(current) != a.quote_sha256:  # any change to the quote voids it (M9.1)
                drift = [Reason("QUOTE_CHANGED", f"quote {a.quote_id} changed after the approval request", ""), *drift]
            if drift:
                meta.reasons = drift
                a = a.model_copy(
                    update={"status": "canceled", "outcome": "voided", "reason_code": "price_changed", **stamp}
                )
                o = _escalate_drift(state, o, drift, a.quote_id)
            else:
                a = a.model_copy(update={"status": "completed", "outcome": "approved", "reason_code": None, **stamp})
                o = transition(o, "ready_for_complete", reason_code=None)
                o = transition(o, "completed", completed_at=now.isoformat())
        state.approvals[approval_id] = a
        state.orders[o.order_id] = o
        return approval_response(state, a)
