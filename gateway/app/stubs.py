"""Contract stubs (PLAN M1.6): canned answers built on the headline example W-03.

Need: 1,000 L lactose-free milk for Mon 16.11.2026, as of Sat 14.11 10:00. Numbers are the live values recorded
in docs/data-and-api-findings.md (W-03, W-05). Real search, offers, quotes, policy and orders replace this module
in M2-M9 behind the same contract. A little state (confirmed quotes, placed orders) lives in memory so a voice
session can walk the whole flow.
"""

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .contract import (
    Approval,
    ApprovalResponse,
    ConfirmResponse,
    ContentPerUnit,
    Evidence,
    Msg,
    NotOffered,
    Offer,
    OffersRequest,
    OffersResponse,
    Order,
    OrderResponse,
    PlanQuantityRequest,
    PlanQuantityResponse,
    ProductResponse,
    ProductSummary,
    Quote,
    QuoteLine,
    QuoteResponse,
    SearchRequest,
    SearchResponse,
    Substitute,
    SubstitutesRequest,
    SubstitutesResponse,
)
from .identity import Buyer

CENT = Decimal("0.01")
DELIVERY = "2026-11-16"
STOCK_CUTOFF = "2026-11-15T17:00:00+02:00"
TERMINAL_CUTOFF = "2026-11-12T15:00:00+02:00"
VAT = Decimal("13.5")


def money(d: Decimal) -> str:
    return str(d.quantize(CENT, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class P:
    id: str
    name: str
    unit: str
    litres: Decimal
    price: Decimal
    net: bool
    stock: str  # untracked | known | unknown_terminal | none
    stock_qty: int | None
    cutoff: str
    variant: bool = False


# W-03 rows used by the stubs (EUR excl. VAT per API unit).
PRODUCTS: dict[str, P] = {
    p.id: p
    for p in [
        P(
            "464306",
            "Valio Hyvä suomalainen Arki Eila kevytmaitojuoma 1 l laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.01"),
            True,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "464401",
            "Valio Hyvä suomalainen Arki Eila rasvaton maitojuoma 1 l laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.10"),
            True,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "464237",
            "Valio kahvimaito 1 l UHT laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.30"),
            True,
            "untracked",
            None,
            STOCK_CUTOFF,
            variant=True,
        ),
        P(
            "463335",
            "Valio Eila 3 % maitojuoma 1 l laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.40"),
            True,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "464201",
            "Valio kevytmaito 1 l UHT laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.56"),
            False,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "464073",
            "Valio täysmaito 1 l UHT laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.64"),
            True,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "464398",
            "Valio Eila kevytmaitojuoma 1 l UHT laktoositon",
            "ST",
            Decimal(1),
            Decimal("1.65"),
            True,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "463779",
            "Valio Eila kevytmaitojuoma 2,5 dl UHT laktoositon",
            "KI",
            Decimal("3.75"),
            Decimal("10.71"),
            False,
            "untracked",
            None,
            STOCK_CUTOFF,
        ),
        P(
            "469363",
            "Arla Kevytmaitojuoma 1 L UHT laktoositon",
            "ST",
            Decimal(1),
            Decimal("2.48"),
            False,
            "known",
            384,
            STOCK_CUTOFF,
        ),
        P(
            "469119",
            "Valio Eila rasvaton maitojuoma 1,75 l laktoositon",
            "ST",
            Decimal("1.75"),
            Decimal("2.08"),
            False,
            "unknown_terminal",
            None,
            TERMINAL_CUTOFF,
        ),
        P(
            "463038",
            "Valio Eila kevytmaitojuoma 10 l novobox laktoositon",
            "KI",
            Decimal(20),
            Decimal("31.31"),
            False,
            "unknown_terminal",
            None,
            TERMINAL_CUTOFF,
        ),
        P(
            "462921",
            "Valio Eila Luomu kevytmaitojuoma 1 l laktoositon",
            "KI",
            Decimal(5),
            Decimal("10.97"),
            False,
            "unknown_terminal",
            None,
            TERMINAL_CUTOFF,
        ),
        P(
            "464440",
            "Valio kevytmaito 0,5 l UHT laktoositon",
            "ST",
            Decimal("0.5"),
            Decimal("0.88"),
            False,
            "none",
            None,
            "",
        ),
    ]
}
ON_TIME = ["464306", "464401", "463335", "464237", "464201", "464073", "464398", "463779"]
TIERS = {"464306": "best", "464401": "better", "463335": "good"}


def summary(p: P) -> ProductSummary:
    return ProductSummary(
        product_id=p.id,
        name_fi=p.name,
        brand="Valio" if "Valio" in p.name else "Arla",
        vendor="VALIO OY TUORE" if "Valio" in p.name else "ARLA OY",
        category="10400",
        sales_unit=p.unit,
        content_per_unit=ContentPerUnit(value=str(p.litres), unit="L", source="vote", confidence="high"),
        claims=["FREE_FROM_LACTOSE"],
        allergens_contains=["AM"],
        allergen_data="declared",
        temperature_class="chilled",
    )


def need_units(p: P, litres: Decimal) -> int:
    return int((litres / p.litres).to_integral_value(rounding=ROUND_CEILING))


def offer(p: P, litres: Decimal, offer_set_id: str) -> Offer:
    qty = need_units(p, litres)
    total = p.price * qty
    flags = ["STOCK_UNTRACKED"] if p.stock == "untracked" else []
    if p.net:
        flags.append("NET_PRICE")
    if p.variant:
        flags.append("VARIANT")
    tier = TIERS.get(p.id, "other")
    per_l = money(p.price / p.litres)
    return Offer(
        offer_id=f"{offer_set_id}:{p.id}",
        tier=tier,
        product_id=p.id,
        name_fi=p.name,
        api_unit=p.unit,
        qty=qty,
        content_total=str(p.litres * qty),
        unit_price_net=money(p.price),
        total_net=money(total),
        price_per_base_unit=per_l,
        base_unit="L",
        delivery_date=DELIVERY,
        order_by=p.cutoff,
        stock=p.stock,
        stock_qty=p.stock_qty,
        flags=flags,
        explanation=Msg(
            fi=f"{p.name}: {qty} × {p.unit}, {money(total)} € alv 0 % ({per_l} €/l). Toimitus ma 16.11. "
            f"Valio Aimon varastosta, tilattava viimeistään su 15.11. klo 17.00.",
            en=f"{p.name}: {qty} × {p.unit}, EUR {money(total)} excl. VAT ({per_l} EUR/L). Delivery Mon 16.11 "
            f"from Valio Aimo stock; order by Sun 15.11 17:00.",
        ),
    )


def search(req: SearchRequest) -> SearchResponse:
    products = [summary(PRODUCTS[i]) for i in ON_TIME][: req.limit]
    return SearchResponse(
        products=products,
        total_matches=29,
        message_for_user=Msg(
            fi="Löysin 29 laktoositonta maitovaihtoehtoa.", en="I found 29 lactose-free milk options."
        ),
        warnings=["stub: search returns the W-03 milk candidates for any query"],
    )


def get_product(product_id: str) -> ProductResponse | None:
    p = PRODUCTS.get(product_id)
    if p is None:
        return None
    s = summary(p)
    json_ld = {
        "@context": {"@vocab": "https://schema.org/", "gs1": "https://ref.gs1.org/voc/"},
        "@type": "Product",
        "identifier": p.id,
        "name": p.name,
        "brand": {"@type": "Brand", "name": s.brand},
        "gs1:nutritionalClaim": "gs1:NutritionalClaimTypeCode-FREE_FROM_LACTOSE",
        "offers": {
            "@type": "Offer",
            "priceCurrency": "EUR",
            "price": money(p.price),
            "priceSpecification": {"@type": "UnitPriceSpecification", "valueAddedTaxIncluded": False},
        },
    }
    return ProductResponse(product=s, json_ld=json_ld, message_for_user=Msg(fi=p.name, en=p.name), warnings=["stub"])


def plan_quantity(req: PlanQuantityRequest) -> PlanQuantityResponse | None:
    p = PRODUCTS.get(req.product_id)
    if p is None:
        return None
    litres = Decimal(str(req.amount))
    qty = need_units(p, litres)
    total = p.litres * qty
    return PlanQuantityResponse(
        product_id=p.id,
        api_unit=p.unit,
        content_per_unit=ContentPerUnit(value=str(p.litres), unit="L", source="vote", confidence="high"),
        units_needed=qty,
        total_content=str(total),
        overshoot=str(total - litres),
        message_for_user=Msg(fi=f"{qty} × {p.unit} = {total} l.", en=f"{qty} × {p.unit} = {total} L."),
        warnings=["stub: litres only"] if req.unit != "L" else ["stub"],
    )


def offers(req: OffersRequest, as_of: str) -> OffersResponse:
    litres = Decimal(str(req.amount))
    key = f"{req.query}|{req.amount}|{req.unit}|{req.need_date}|{req.allow_variants}"
    offer_set_id = "OS-" + hashlib.sha256(key.encode()).hexdigest()[:8].upper()
    ids = [i for i in ON_TIME if req.allow_variants or not PRODUCTS[i].variant]
    options = [offer(PRODUCTS[i], litres, offer_set_id) for i in ids]
    cutoff = Msg(
        fi="Toimittajan tilausaika ma 16.11. toimitukseen päättyi to 12.11. klo 15.00.",
        en="The supplier cut-off for Monday delivery passed on Thu 12.11 at 15:00.",
    )
    not_offered = [
        NotOffered(product_id=i, name_fi=PRODUCTS[i].name, flags=["CUTOFF_PASSED"], reason=cutoff)
        for i in ["469119", "463038", "462921"]
    ] + [
        NotOffered(
            product_id="469363",
            name_fi=PRODUCTS["469363"].name,
            flags=["PARTIAL_STOCK"],
            reason=Msg(fi="Varastossa vain 384 kpl.", en="Only 384 units in stock."),
        ),
        NotOffered(
            product_id="464440",
            name_fi=PRODUCTS["464440"].name,
            flags=["NOT_DELIVERABLE"],
            reason=Msg(fi="Ei toimitettavissa.", en="Cannot be delivered on any date."),
        ),
    ]
    best = options[0]
    return OffersResponse(
        offer_set_id=offer_set_id,
        need={"amount": req.amount, "unit": req.unit, "need_date": req.need_date, "claims": ["FREE_FROM_LACTOSE"]},
        as_of=as_of,
        options=options,
        not_offered=not_offered,
        counts={"candidates": 29, "on_time_full": 8, "partial": 4, "cutoff_passed": 16, "not_deliverable": 1},
        message_for_user=Msg(
            fi=f"Paras ajoissa toimitettava vaihtoehto on {best.qty} × {best.name_fi}, {best.total_net} € alv 0 %, "
            "tilattava su 15.11. klo 17.00 mennessä. Huomaa, että se on maitojuoma. Isot 10 litran laatikot tulevat "
            "toimittajan varastosta, ja niiden tilausaika on jo mennyt.",
            en=f"The best on-time option is {best.qty} × {best.name_fi}, EUR {best.total_net} excl. VAT, to be ordered "
            "by Sun 15.11 17:00. Note that it is a milk drink (maitojuoma). The bulk 10 L boxes come from supplier "
            "warehouses and their cut-off has already passed.",
        ),
        warnings=[
            "Stock is not tracked for the Valio options: shown as 'not tracked', not as a number.",
            "stub: canned W-03 options",
        ],
    )


def substitutes(req: SubstitutesRequest) -> SubstitutesResponse:
    litres = Decimal(str(req.amount))
    subs = [
        Substitute(
            product_id="464398",
            name_fi=PRODUCTS["464398"].name,
            risk_tags=["needs_approval"],
            offer=offer(PRODUCTS["464398"], litres, "OS-SUBST"),
        )
    ]
    return SubstitutesResponse(
        original_product_id=req.product_id,
        substitutes=subs,
        message_for_user=Msg(
            fi="Turvallinen korvaava tuote löytyi; korvaaminen vaatii hyväksynnän.",
            en="One safe substitute found; any substitution needs approval.",
        ),
        warnings=["stub"],
    )


class StubState:
    """Quotes and orders, in memory. Idempotent by (buyer, offer) and (conversation or buyer, quote)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.quotes: dict[str, Quote] = {}
        self.orders: dict[str, Order] = {}
        self.approvals: dict[str, Approval] = {}
        self.offers: dict[str, Offer] = {}
        self.offer_sets: dict[str, OffersResponse] = {}

    def get_offers(self, req: OffersRequest, as_of: str) -> OffersResponse:
        res = offers(req, as_of)
        with self.lock:
            self.offers.update({o.offer_id: o for o in res.options})
            self.offer_sets[res.offer_set_id] = res
        return res

    def get_offer_set(self, offer_set_id: str) -> OffersResponse | None:
        return self.offer_sets.get(offer_set_id)

    def create_quote(self, buyer: Buyer, offer_id: str, as_of: str) -> QuoteResponse | None:
        o = self.offers.get(offer_id)
        p = PRODUCTS.get(o.product_id) if o else None
        if o is None or p is None:
            return None
        quote_id = "Q-" + hashlib.sha256(f"{buyer.buyer_id}|{offer_id}".encode()).hexdigest()[:10].upper()
        with self.lock:
            q = self.quotes.get(quote_id)
            if q is None:
                qty = o.qty
                line_net = p.price * qty
                line_vat = (line_net * VAT / 100).quantize(CENT, rounding=ROUND_HALF_UP)
                issued = datetime.fromisoformat(as_of)
                q = Quote(
                    quote_id=quote_id,
                    status="ready_for_complete",
                    buyer_id=buyer.buyer_id,
                    lines=[
                        QuoteLine(
                            line_id=1,
                            product_id=p.id,
                            name_fi=p.name,
                            api_unit=p.unit,
                            qty=qty,
                            unit_price_net=money(p.price),
                            line_net=money(line_net),
                            vat_rate=str(VAT),
                            line_vat=money(line_vat),
                            line_gross=money(line_net + line_vat),
                            delivery_date=o.delivery_date,
                        )
                    ],
                    total_net=money(line_net),
                    total_vat=money(line_vat),
                    total_gross=money(line_net + line_vat),
                    delivery_date=DELIVERY,
                    issued_at=issued.isoformat(),
                    expires_at=(issued + timedelta(minutes=15)).isoformat(),
                    evidence=Evidence(api_time_now="2026-11-14T01:16:59+0200", stub=True),
                )
                self.quotes[quote_id] = q
        return QuoteResponse(
            status=q.status,
            quote_id=q.quote_id,
            quote=q,
            total_net=q.total_net,
            total_gross=q.total_gross,
            expires_at=q.expires_at,
            message_for_user=Msg(
                fi=f"Tarjous {q.quote_id}: {q.lines[0].qty} × {q.lines[0].name_fi}, {q.total_net} € alv 0 % "
                f"({q.total_gross} € sis. alv). Hinta on kiinteä {q.expires_at[11:16]} asti. Vahvista tilaus näytöltä.",
                en=f"Quote {q.quote_id}: {q.lines[0].qty} × {q.lines[0].name_fi}, EUR {q.total_net} excl. VAT "
                f"(EUR {q.total_gross} incl. VAT). The price is fixed until {q.expires_at[11:16]}. Please confirm on "
                "screen.",
            ),
            warnings=["stub: quote is not signed yet (M6)"],
        )

    def get_quote(self, buyer: Buyer, quote_id: str) -> Quote | None:
        q = self.quotes.get(quote_id)
        return q if q is not None and q.buyer_id == buyer.buyer_id else None

    def confirm(self, buyer: Buyer, quote_id: str, now: str) -> ConfirmResponse | None:
        with self.lock:
            q = self.get_quote(buyer, quote_id)
            if q is None:
                return None
            if not q.confirmed:
                q = q.model_copy(update={"confirmed": True, "confirmed_at": now})
                self.quotes[quote_id] = q
        return ConfirmResponse(
            quote_id=quote_id,
            confirmed=True,
            confirmation_ref="C-" + quote_id[2:],
            message_for_user=Msg(fi="Vahvistettu.", en="Confirmed."),
        )

    def place_order(self, buyer: Buyer, quote_id: str, idem: str, as_of: str) -> OrderResponse:
        with self.lock:
            q = self.get_quote(buyer, quote_id)
            if q is None:
                return OrderResponse(
                    status="incomplete",
                    reason_code="not_found",
                    message_for_user=Msg(
                        fi="Tarjousta ei löytynyt. Pyydä uusi tarjous.",
                        en="I could not find that quote. Let's make a new one.",
                    ),
                )
            if not q.confirmed:
                return OrderResponse(
                    status="incomplete",
                    reason_code="confirmation_required",
                    message_for_user=Msg(
                        fi="Tilaus pitää ensin vahvistaa näytöltä.",
                        en="The buyer must confirm the quote on screen first.",
                    ),
                )
            order_id = "O-" + hashlib.sha256(idem.encode()).hexdigest()[:10].upper()
            o = self.orders.get(order_id)
            if o is None:
                approval_id = "A-" + order_id[2:]
                decide_by = "2026-11-15T16:00:00+02:00"
                o = Order(
                    order_id=order_id,
                    quote_id=quote_id,
                    status="requires_escalation",
                    total_net=q.total_net,
                    total_gross=q.total_gross,
                    delivery_date=q.delivery_date,
                    approval_id=approval_id,
                    approval_url=f"/approvals/{approval_id}",
                    created_at=as_of,
                )
                self.orders[order_id] = o
                self.approvals[approval_id] = Approval(
                    approval_id=approval_id,
                    status="requires_escalation",
                    order_id=order_id,
                    quote_id=quote_id,
                    reasons=[f"OVER_ORDER_CAP: EUR {q.total_net} is above the EUR {buyer.order_cap_eur} order cap"],
                    decide_by=decide_by,
                    approver_role="head_chef",
                )
        return self.order_response(o, buyer)

    def order_response(self, o: Order, buyer: Buyer) -> OrderResponse:
        if o.status == "requires_escalation":
            msg = Msg(
                fi=f"Tilaus {o.total_net} € ylittää {buyer.order_cap_eur} euron tilausrajasi, joten se lähti "
                "esihenkilösi hyväksyttäväksi. Hyväksyntä tarvitaan su 15.11. klo 16.00 mennessä.",
                en=f"The order of EUR {o.total_net} is above your EUR {buyer.order_cap_eur} order cap, so it went to "
                "your manager for approval. It needs approval by Sun 15.11 16:00.",
            )
            reason = "limit_exceeded"
        elif o.status == "canceled":
            msg, reason = Msg(fi="Tilaus on peruttu.", en="The order is canceled."), None
        else:
            msg, reason = Msg(fi=f"Tilaus {o.order_id} on vahvistettu.", en=f"Order {o.order_id} is confirmed."), None
        return OrderResponse(
            status=o.status,
            reason_code=reason,
            order_id=o.order_id,
            order=o,
            approval_id=o.approval_id,
            approval_url=o.approval_url,
            total_net=o.total_net,
            message_for_user=msg,
            warnings=["stub: policy and approval are canned until M7-M9"],
        )

    def get_order(self, buyer: Buyer, order_id: str) -> OrderResponse | None:
        o = self.orders.get(order_id)
        if o is None or self.get_quote(buyer, o.quote_id) is None:
            return None
        return self.order_response(o, buyer)

    def cancel_order(self, buyer: Buyer, order_id: str) -> OrderResponse | None:
        with self.lock:
            o = self.orders.get(order_id)
            if o is None or self.get_quote(buyer, o.quote_id) is None:
                return None
            if o.status != "completed":
                o = o.model_copy(update={"status": "canceled"})
                self.orders[order_id] = o
        return self.order_response(o, buyer)

    def get_approval(self, buyer: Buyer, approval_id: str) -> ApprovalResponse | None:
        a = self.approvals.get(approval_id)
        if a is None or self.get_quote(buyer, a.quote_id) is None:
            return None
        return ApprovalResponse(
            status=a.status,
            approval_id=a.approval_id,
            approval=a,
            message_for_user=Msg(fi="Odottaa esihenkilön hyväksyntää.", en="Waiting for the manager's approval."),
        )
