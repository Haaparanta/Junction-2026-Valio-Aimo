"""Contract stubs (PLAN M1.6, basket-plan B-10): a small catalogue, offers computed from it, quotes and orders.

The headline example W-03 still holds: 1,000 L lactose-free milk for Mon 16.11.2026, as of Sat 14.11 10:00, gives
1,000 x 464306 for EUR 1,010.00. Values recorded in docs/data-and-api-findings.md are used where they exist (the W-03
milks; 464076, 463233, 469346, 470961, 460603, 476738, 465244, 460675 and the other X-fixture values). Rows with any
invented value carry invented=True, and every response that shows such a row says so in `warnings`.

Real search, offers, quotes, policy and orders replace this module in M2-M9 behind the same contract. A little state
(offers, quotes, orders) lives in memory so a voice session can walk the whole flow.
"""

import hashlib
import math
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from .contract import (
    Approval,
    Basket,
    ConfirmResponse,
    ContentPerUnit,
    Evidence,
    Msg,
    NotOffered,
    Offer,
    OfferFlag,
    OffersRequest,
    OffersResponse,
    Order,
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
from .fmt import CENT, UNIT_EN, UNIT_FI, at_en, at_fi, day_en, day_fi, fi, helsinki_at, instant, money, num, quoted
from .identity import Buyer
from .signing import TYP_QUOTE, canonical, keys, quote_document, sha256_hex

FOOD_VAT = Decimal("13.5")
BaseUnit = Literal["L", "KG", "PCS"]
Logistics = Literal["stock", "terminal", "none"]
# Lead time per logistic model (A-03, F-05): Valio Aimo stock by 17:00 the day before, a supplier's warehouse
# (Terminal) by 15:00 four days before. A row may carry its vendor's own cut-off hour (460675: 13:00).
LEAD = {"stock": (1, "17:00"), "terminal": (4, "15:00")}


@dataclass(frozen=True)
class P:
    """One catalogue row. Price is EUR excl. VAT per API unit; content is base units (L, KG or PCS) per API unit."""

    id: str
    name: str
    api_unit: str  # the unit of price and amount in the API (scheduleLines[].salesUnit)
    content: Decimal
    price: Decimal
    net: bool  # a customer net price (netPriceFound)
    logistics: Logistics  # stock | terminal | none (empty scheduleLines: not deliverable on any date)
    stock: Literal["untracked", "known", "none"] = "untracked"  # Valio Aimo stock only
    stock_qty: int | None = None  # with stock "known", in API units
    base_unit: BaseUnit = "L"
    catalogue_unit: str | None = None  # the catalogue salesUnit when it differs from the API unit (UNIT_MISMATCH)
    catalogue_content: Decimal | None = None  # base units per catalogue unit, when that unit differs
    vat: Decimal = FOOD_VAT
    claims: tuple[str, ...] = ()  # GS1 nutritional claims
    allergens: tuple[str, ...] = ()  # GS1 allergen codes the product contains
    allergen_data: Literal["declared", "unknown"] = "declared"  # unknown is never safe (S-05)
    temperature: Literal["chilled", "frozen", "ambient", "unknown"] = "chilled"
    category: str = ""
    brand: str | None = None
    vendor: str | None = None
    variant: bool = False  # coffee milk, portion packs: offered only with allow_variants
    invented: bool = False  # some value is not in the findings
    lot: int = 1  # order step in API units (460675: lot 10 KG)
    cutoff: str | None = None  # HH:MM when the vendor's cut-off hour differs from the logistic model's
    catch_weight: bool = False  # invoiced by actual weight

    @property
    def sales_unit(self) -> str:
        return self.catalogue_unit or self.api_unit


def _milk(
    pid: str,
    name: str,
    unit: str,
    litres: str,
    price: str,
    net: bool,
    logistics: Logistics,
    *,
    stock: Literal["untracked", "known", "none"] = "untracked",
    stock_qty: int | None = None,
    variant: bool = False,
) -> P:
    """A W-03 lactose-free milk (findings W-01..W-03): FREE_FROM_LACTOSE, contains milk (AM), category 10400."""
    arla = name.startswith("Arla")
    return P(
        pid,
        name,
        unit,
        Decimal(litres),
        Decimal(price),
        net,
        logistics,
        stock=stock,
        stock_qty=stock_qty,
        claims=("FREE_FROM_LACTOSE",),
        allergens=("AM",),
        category="10400",
        brand="Arla" if arla else "Valio",
        vendor="ARLA OY" if arla else "VALIO OY TUORE",
        variant=variant,
    )


LF = ("FREE_FROM_LACTOSE",)
AM = ("AM",)
VALIO = {"brand": "Valio", "vendor": "VALIO OY TUORE"}
ARLA = {"brand": "Arla", "vendor": "ARLA OY"}
D = Decimal

# fmt: off
PRODUCTS: dict[str, P] = {p.id: p for p in [
    # ---- W-03 milks: the live values, unchanged ----------------------------------------------------------
    _milk("464306", "Valio Hyvä suomalainen Arki Eila kevytmaitojuoma 1 l laktoositon", "ST", "1", "1.01",
          True, "stock"),
    _milk("464401", "Valio Hyvä suomalainen Arki Eila rasvaton maitojuoma 1 l laktoositon", "ST", "1", "1.10",
          True, "stock"),
    _milk("464237", "Valio kahvimaito 1 l UHT laktoositon", "ST", "1", "1.30", True, "stock", variant=True),
    _milk("463335", "Valio Eila 3 % maitojuoma 1 l laktoositon", "ST", "1", "1.40", True, "stock"),
    _milk("464201", "Valio kevytmaito 1 l UHT laktoositon", "ST", "1", "1.56", False, "stock"),
    _milk("464073", "Valio täysmaito 1 l UHT laktoositon", "ST", "1", "1.64", True, "stock"),
    _milk("464398", "Valio Eila kevytmaitojuoma 1 l UHT laktoositon", "ST", "1", "1.65", True, "stock"),
    _milk("463779", "Valio Eila kevytmaitojuoma 2,5 dl UHT laktoositon", "KI", "3.75", "10.71", False, "stock"),
    _milk("469363", "Arla Kevytmaitojuoma 1 L UHT laktoositon", "ST", "1", "2.48", False, "stock",
          stock="known", stock_qty=384),
    _milk("469119", "Valio Eila rasvaton maitojuoma 1,75 l laktoositon", "ST", "1.75", "2.08", False, "terminal"),
    _milk("463038", "Valio Eila kevytmaitojuoma 10 l novobox laktoositon", "KI", "20", "31.31", False, "terminal"),
    _milk("462921", "Valio Eila Luomu kevytmaitojuoma 1 l laktoositon", "KI", "5", "10.97", False, "terminal"),
    _milk("464440", "Valio kevytmaito 0,5 l UHT laktoositon", "ST", "0.5", "0.88", False, "none", stock="none"),
    # ---- the basket demos (B-10); each row has invented values, the recorded ones are noted --------------
    # A-08, X-14: catalogue ST = 0.5 L but the API unit is KI = 3.0 L at 6.22, Terminal. Claims inferred.
    P("465244", "Arla 5 dl kevytmaito", "KI", D(3), D("6.22"), False, "terminal",
      catalogue_unit="ST", catalogue_content=D("0.5"), allergens=AM, category="10400", invented=True, **ARLA),
    # D-06: ST of 5.0 kg at 37.33 (the data's 20 kg is wrong). Logistics and the claim invented.
    P("464076", "Valio Eila voi 4x5 kg", "ST", D(5), D("37.33"), False, "stock",
      base_unit="KG", claims=LF, allergens=AM, category="10510", invented=True, **VALIO),
    # X-21: KI = 2.1 kg of 10 g portions at 23.42; portion packs are a variant.
    P("463233", "Valio voi 10 g", "KI", D("2.1"), D("23.42"), False, "stock",
      base_unit="KG", claims=LF, allergens=AM, category="10510", variant=True, invented=True, **VALIO),
    P("467310", "Valio Eila laktoositon vispikerma 35 % 1 l UHT", "ST", D(1), D("5.42"), False, "stock",
      claims=LF, allergens=AM, category="10401", invented=True, **VALIO),
    # X-10: Stock 48 ST. Name and price invented.
    P("469346", "Arla Laktoositon kuohukerma 38 % 1 L", "ST", D(1), D("5.12"), False, "stock",
      stock="known", stock_qty=48, claims=LF, allergens=AM, category="10401", invented=True, **ARLA),
    P("467318", "Valio kuohukerma 38 % 1 l", "ST", D(1), D("4.65"), False, "stock",
      allergens=AM, category="10401", invented=True, **VALIO),
    # D-02: a minimal ERP record, ALL-CAPS, with no brand, claims or allergen data.
    P("461755", "VISPIKERMA 35% 1L", "ST", D(1), D("3.89"), False, "stock",
      allergen_data="unknown", category="10401", invented=True),
    # D-05 names 469338 as an Edam.
    P("469338", "Valio Edam 24 % juusto 1,3 kg", "ST", D("1.3"), D("11.96"), False, "stock",
      base_unit="KG", claims=LF, allergens=AM, category="10600", invented=True, **VALIO),
    P("465731", "Valio laktoositon maitorahka 1 kg", "ST", D(1), D("3.48"), False, "stock",
      base_unit="KG", claims=LF, allergens=AM, category="10430", invented=True, **VALIO),
    # D-06, X-23: 0.91 EUR and empty scheduleLines, so never deliverable. Content from the name.
    P("476738", "Arla Kalinka smetana 150 g", "ST", D("0.15"), D("0.91"), False, "none",
      stock="none", base_unit="KG", allergens=AM, category="10420", invented=True, **ARLA),
    # D-08 names 472535 as eggs with temperature code 6 (cool to ambient, no label).
    P("472535", "Munakunta kananmuna M90", "KI", D(90), D("18.90"), False, "stock",
      base_unit="PCS", allergens=("AE",), temperature="unknown", category="10590",
      brand="Munakunta", vendor="MUNAKUNTA OY TUORE", invented=True),
    P("470212", "Myllyn Paras vehnäjauho 2 kg", "ST", D(2), D("2.04"), False, "stock",
      base_unit="KG", allergens=("AW", "UW"), temperature="ambient", category="21110",
      brand="Myllyn Paras", vendor="MYLLYN PARAS OY KUIVA", invented=True),
    P("473305", "Semper gluteeniton jauhoseos 1 kg", "ST", D(1), D("4.85"), False, "stock",
      base_unit="KG", claims=("FREE_FROM_GLUTEN",), temperature="ambient", category="21110",
      brand="Semper", vendor="SEMPER AB KUIVA", invented=True),
    P("470415", "Finnamyl perunajauho 1 kg", "ST", D(1), D("2.38"), False, "stock",
      base_unit="KG", claims=("FREE_FROM_GLUTEN",), temperature="ambient", category="21110",
      brand="Finnamyl", vendor="FINNAMYL OY KUIVA", invented=True),
    P("468904", "Dansukker taloussokeri 1 kg", "ST", D(1), D("1.22"), False, "stock",
      base_unit="KG", temperature="ambient", category="21310",
      brand="Dansukker", vendor="NORDIC SUGAR OY KUIVA", invented=True),
    P("468911", "Dansukker tomusokeri 1 kg", "ST", D(1), D("1.95"), False, "stock",
      base_unit="KG", temperature="ambient", category="21310",
      brand="Dansukker", vendor="NORDIC SUGAR OY KUIVA", invented=True),
    P("466932", "Pakkasmarja mansikka 2,5 kg pakaste", "ST", D("2.5"), D("13.70"), False, "stock",
      base_unit="KG", temperature="frozen", category="41510",
      brand="Pakkasmarja", vendor="PAKKASMARJA OY PAKASTE", invented=True),
    # A dish plan for mansikkakakku asks for fresh strawberries and strawberry jam; both rows invented.
    P("471820", "Tuore kotimainen mansikka 2 kg", "ST", D(2), D("17.80"), False, "stock",
      base_unit="KG", category="13410", invented=True),
    P("471837", "Mansikkahillo 3 kg", "ST", D(3), D("13.20"), False, "stock",
      base_unit="KG", temperature="ambient", category="22410", invented=True),
    # X-30: 0.65 EUR/kg, Stock. The name and the 25 kg sack invented.
    P("470961", "Yleisperuna 25 kg", "SK", D(25), D("16.25"), False, "stock",
      base_unit="KG", temperature="unknown", category="13110", invented=True),
    # A-05, X-30: 3.62 EUR/kg, Stock untracked, SK = 5. The name invented.
    P("460603", "Kuorittu annosperuna 5 kg", "SK", D(5), D("18.10"), False, "stock",
      base_unit="KG", category="13110", invented=True),
    # X-31: 104.52 per KI, Stock 585 KI, organic and Fairtrade labels; that it is coffee is inferred.
    P("464322", "Paulig Luomu Reilu kauppa suodatinkahvi 6 x 1 kg", "KI", D(6), D("104.52"), False, "stock",
      stock="known", stock_qty=585, base_unit="KG", temperature="ambient", category="22110",
      brand="Paulig", vendor="PAULIG OY KUIVA", invented=True),
    # X-31: 98.27 per KI, Stock 40 KI; coffee inferred.
    P("470153", "Paulig Juhla Mokka suodatinkahvi 6 x 1 kg", "KI", D(6), D("98.27"), False, "stock",
      stock="known", stock_qty=40, base_unit="KG", temperature="ambient", category="22110",
      brand="Paulig", vendor="PAULIG OY KUIVA", invented=True),
    # D-07, F-02, X-15: KG at 29.17, lot 10, frozen, Terminal closing 13:00, catch weight. Allergens inferred.
    P("460675", "Snellman Flank steak n2kg", "KG", D(1), D("29.17"), False, "terminal",
      base_unit="KG", temperature="frozen", category="41720", lot=10, cutoff="13:00", catch_weight=True,
      brand="Snellman", vendor="SNELLMANIN LIHANJALOSTUS OY PAKASTE", invented=True),
]}
# fmt: on

# With empty heads the last word of the query is the head; English words map to the Finnish head (S-03).
EN_HEADS = {
    "milk": "maito",
    "cream": "kerma",
    "butter": "voi",
    "cheese": "juusto",
    "egg": "kananmuna",
    "eggs": "kananmuna",
    "flour": "jauho",
    "sugar": "sokeri",
    "potato": "peruna",
    "potatoes": "peruna",
    "coffee": "kahvi",
    "strawberry": "mansikka",
    "strawberries": "mansikka",
    "quark": "rahka",
}
WORD = re.compile(r"[^\W\d_]+")
TIER_NAMES: list[Literal["best", "better", "good"]] = ["best", "better", "good"]
COUNT_KEY = {  # the one count a refused row adds to, by its first blocking flag
    "NOT_DELIVERABLE": "not_deliverable",
    "CUTOFF_PASSED": "cutoff_passed",
    "OUT_OF_STOCK": "out_of_stock",
    "PARTIAL_STOCK": "partial",
}
COUNTS = ["candidates", "on_time_full", "partial", "cutoff_passed", "not_deliverable", "out_of_stock"]


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def vat_of(net: Decimal, rate: Decimal) -> Decimal:
    """VAT on a line's net total, rounded half-up to cents (F-06)."""
    return (net * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)


# ---- quote evidence and validity (PLAN M6.2, M6.4; findings A-01, F-07) ------------------------------------

API_TIME_NOW = "2026-11-14T01:16:59+0200"  # the recorded timeNow of the snapshot the stub rows come from (A-01)
QUOTE_TTL = timedelta(minutes=15)  # a quoted price holds at most this long after issue
NET_VALID_TO = date(2026, 12, 31)  # customer net prices seen end 2026-12-31 (A-12); validTo inclusive until Q-06


def valid_to(p: P) -> date | None:
    """The last delivery date the row's price holds for: net prices are time-boxed, list prices are not (F-07)."""
    return NET_VALID_TO if p.net else None


def quote_expiry(issued: datetime, lines: Iterable[tuple[str, str]]) -> datetime:
    """expiresAt = min(cut-off, end of the validTo day, issue + TTL) over the (product_id, delivery_date) lines."""
    times = [issued + QUOTE_TTL]
    for product_id, delivery in lines:
        p = PRODUCTS.get(product_id)
        if p is None:
            continue
        if (ob := order_by(p, date.fromisoformat(delivery))) is not None:
            times.append(ob)
        if (vt := valid_to(p)) is not None:
            times.append(helsinki_at(vt + timedelta(days=1), "00:00"))  # the end of the validTo day, Helsinki
    return min(times)


def stub_responses(lines: list[QuoteLine]) -> tuple[dict, dict]:
    """The /price and /availability answers the quote's lines were read from, as the stub rows stand for them."""
    rows = [(x, PRODUCTS[x.product_id]) for x in lines if x.product_id in PRODUCTS]
    price = {
        "timeNow": API_TIME_NOW,
        "products": [
            {
                "productId": p.id,
                "salesUnit": p.api_unit,
                "catalogPrice": {"value": money(p.price)},
                "netPriceFound": p.net,
                "tax": {"taxRate": str(p.vat)},
            }
            for _, p in rows
        ],
    }
    availability = {
        "timeNow": API_TIME_NOW,
        "products": [
            {
                "productId": p.id,
                "requestedDate": x.delivery_date,
                "logisticModel": p.logistics,
                "closingTime": ob.isoformat() if (ob := order_by(p, date.fromisoformat(x.delivery_date))) else None,
                "stock": p.stock,
                "stockQty": p.stock_qty,
            }
            for x, p in rows
        ],
    }
    return price, availability


def stub_evidence(lines: list[QuoteLine]) -> Evidence:
    """Which snapshot a quote came from (M6.2): the API's timeNow and the SHA-256 of each canonical response."""
    return Evidence(
        api_time_now=API_TIME_NOW,
        response_sha256=[sha256_hex(canonical(r)) for r in stub_responses(lines)],
        stub=True,
    )


def sign_quote(q: Quote) -> Quote:
    """Set quote_jws: ES256 over the canonical quote without its jws field and confirmation state (M6.3)."""
    return q.model_copy(update={"quote_jws": keys().quotes.sign(quote_document(q), TYP_QUOTE)})


def invented_warnings(ids: Iterable[str | None]) -> list[str]:
    """One 'stub: invented catalogue values' warning per invented row a response shows."""
    shown = {i for i in ids if i and i in PRODUCTS and PRODUCTS[i].invented}
    return [f"stub: invented catalogue values for {i}" for i in sorted(shown)]


# ---- catalogue -----------------------------------------------------------------------------------


def summary(p: P) -> ProductSummary:
    content = p.catalogue_content or p.content
    return ProductSummary(
        product_id=p.id,
        name_fi=p.name,
        brand=p.brand,
        vendor=p.vendor,
        category=p.category,
        sales_unit=p.sales_unit,
        content_per_unit=ContentPerUnit(
            value=num(content), unit=p.base_unit, source="name" if p.invented else "vote", confidence="high"
        ),
        claims=list(p.claims),
        allergens_contains=list(p.allergens),
        allergen_data=p.allergen_data,
        temperature_class=p.temperature,
    )


def words(text: str) -> list[str]:
    return WORD.findall(text.casefold())


def heads_for(req: SearchRequest) -> list[str]:
    """The heads to match, in Finnish base form. Each head counts by its last word; '' never matches everything."""
    heads = [w[-1] for w in (words(h) for h in req.heads) if w]
    if heads:
        return heads
    last = words(req.query)[-1:] or [""]
    head = EN_HEADS.get(last[0], last[0])
    return [head] if head else []


def matches(req: SearchRequest, heads: list[str]) -> list[P]:
    """Catalogue rows for a need: head on the end of a name word (Finnish compounds), then the hard filters (S-05)."""
    exclude = [x.strip().casefold() for x in req.exclude if x.strip()]
    claims = {c.strip().upper() for c in req.must_claims if c.strip()}
    banned = {a.strip().upper() for a in req.must_not_allergens if a.strip()}
    rows = []
    for p in PRODUCTS.values():
        name = p.name.casefold()
        if not any(w.endswith(h) for w in words(p.name) for h in heads):
            continue
        if any(x in name for x in exclude) or not claims <= set(p.claims):
            continue
        if banned and (p.allergen_data == "unknown" or banned & set(p.allergens)):
            continue  # unknown allergen data is never safe
        if req.temperature != "any" and p.temperature not in (req.temperature, "unknown"):
            continue  # an unknown temperature class is not a mismatch (D-08)
        rows.append(p)
    return sorted(rows, key=rank)


def rank(p: P) -> tuple[Decimal, str]:
    return p.price / p.content, p.id


def search(req: SearchRequest) -> SearchResponse:
    rows = matches(req, heads_for(req))
    shown = rows[: req.limit]
    n = len(rows)
    if n == 0:
        msg = Msg(fi="En löytänyt sopivaa tuotetta.", en="I found no matching product.")
    elif n == 1:
        msg = Msg(fi="Löysin 1 sopivan tuotteen.", en="I found 1 matching product.")
    else:
        msg = Msg(fi=f"Löysin {n} sopivaa tuotetta.", en=f"I found {n} matching products.")
    return SearchResponse(
        products=[summary(p) for p in shown],
        total_matches=n,
        message_for_user=msg,
        warnings=["stub: search filters the stub catalogue until M4", *invented_warnings(p.id for p in shown)],
    )


def get_product(product_id: str) -> ProductResponse | None:
    p = PRODUCTS.get(product_id)
    if p is None:
        return None
    s = summary(p)
    json_ld: dict = {
        "@context": {"@vocab": "https://schema.org/", "gs1": "https://ref.gs1.org/voc/"},
        "@type": "Product",
        "identifier": p.id,
        "name": p.name,
    }
    if s.brand:
        json_ld["brand"] = {"@type": "Brand", "name": s.brand}
    claims = [f"gs1:NutritionalClaimTypeCode-{c}" for c in p.claims]
    if claims:
        json_ld["gs1:nutritionalClaim"] = claims[0] if len(claims) == 1 else claims
    json_ld["offers"] = {
        "@type": "Offer",
        "priceCurrency": "EUR",
        "price": money(p.price),
        "priceSpecification": {"@type": "UnitPriceSpecification", "valueAddedTaxIncluded": False},
    }
    return ProductResponse(
        product=s,
        json_ld=json_ld,
        message_for_user=Msg(fi=p.name, en=p.name),
        warnings=["stub", *invented_warnings([p.id])],
    )


def need_units(p: P, amount: Decimal) -> int:
    """Whole API units, in steps of the row's lot (F-02)."""
    return math.ceil(amount / (p.content * p.lot)) * p.lot


def plan_quantity(req: PlanQuantityRequest) -> PlanQuantityResponse | None:
    p = PRODUCTS.get(req.product_id)
    if p is None:
        return None
    amount = Decimal(str(req.amount))
    cpu = ContentPerUnit(
        value=num(p.content), unit=p.base_unit, source="name" if p.invented else "vote", confidence="high"
    )
    warnings = ["stub", *invented_warnings([p.id])]
    if req.unit != p.base_unit:
        return PlanQuantityResponse(
            product_id=p.id,
            api_unit=p.api_unit,
            content_per_unit=cpu,
            units_needed=0,
            total_content="0",
            overshoot="0",
            message_for_user=Msg(
                fi=f"Tuote {quoted(p.name)} hinnoitellaan yksikössä {p.base_unit}. Anna määrä yksikössä {p.base_unit}.",
                en=f"{quoted(p.name)} is priced per {p.base_unit}. Give the amount in {p.base_unit}.",
            ),
            warnings=[*warnings, f"unit mismatch: the amount is in {req.unit}, the product in {p.base_unit}"],
        )
    qty = need_units(p, amount)
    total = p.content * qty
    return PlanQuantityResponse(
        product_id=p.id,
        api_unit=p.api_unit,
        content_per_unit=cpu,
        units_needed=qty,
        total_content=num(total),
        overshoot=num(total - amount),
        message_for_user=Msg(
            fi=f"{qty} × {p.api_unit} = {fi(num(total))} {UNIT_FI[p.base_unit]}.",
            en=f"{qty} × {p.api_unit} = {num(total)} {UNIT_EN[p.base_unit]}.",
        ),
        warnings=warnings,
    )


# ---- offers --------------------------------------------------------------------------------------


def order_by(p: P, need_date: date) -> datetime | None:
    """The cut-off for delivery on need_date, in Helsinki time; None when the row cannot be delivered at all."""
    if p.logistics == "none":
        return None
    days, hhmm = LEAD[p.logistics]
    return helsinki_at(need_date - timedelta(days=days), p.cutoff or hhmm)


def assess(p: P, amount: Decimal, need_date: date, now: datetime) -> tuple[int, datetime | None, list[OfferFlag]]:
    """Units needed, the order-by time and the flags that block delivering the full amount on need_date (F-04)."""
    qty = need_units(p, amount)
    ob = order_by(p, need_date)
    blocking: list[OfferFlag] = []
    if ob is None:
        blocking.append("NOT_DELIVERABLE")
    else:
        if ob <= now:
            blocking.append("CUTOFF_PASSED")
        if p.logistics == "stock" and p.stock == "none":
            blocking.append("OUT_OF_STOCK")
        elif p.logistics == "stock" and p.stock == "known" and (p.stock_qty or 0) < qty:
            blocking.append("PARTIAL_STOCK")
    return qty, ob, blocking


def offer_stock(p: P) -> Literal["untracked", "known", "unknown_terminal", "none"]:
    if p.logistics == "terminal":
        return "unknown_terminal"
    if p.logistics == "none":
        return "none"
    return p.stock


def explanation(p: P, qty: int, need_date: date, ob: datetime) -> Msg:
    total, ppu = money(p.price * qty), money(p.price / p.content)
    ufi, uen = UNIT_FI[p.base_unit], UNIT_EN[p.base_unit]
    src_fi, src_en = (
        ("Valio Aimon varastosta", "from Valio Aimo stock")
        if p.logistics == "stock"
        else ("toimittajan varastosta", "from the supplier's warehouse")
    )
    f = (
        f"{quoted(p.name)}: {qty} × {p.api_unit}, {fi(total)} € alv 0 % ({fi(ppu)} €/{ufi}). "
        f"Toimitus {day_fi(need_date)} {src_fi}, tilattava viimeistään {at_fi(ob)}."
    )
    e = (
        f"{quoted(p.name)}: {qty} × {p.api_unit}, EUR {total} excl. VAT ({ppu} EUR/{uen}). "
        f"Delivery {day_en(need_date)} {src_en}; order by {at_en(ob)}."
    )
    if p.logistics == "stock" and p.stock == "known":
        f += f" Varastossa {p.stock_qty} × {p.api_unit}."
        e += f" {p.stock_qty} × {p.api_unit} in stock."
    if p.sales_unit != p.api_unit:
        f += f" Hinta on yksiköltä {p.api_unit} ({fi(num(p.content))} {ufi}); luettelon myyntiyksikkö: {p.sales_unit}."
        e += f" The price is per {p.api_unit} ({num(p.content)} {uen}); the catalogue sells it per {p.sales_unit}."
    if p.lot > 1:
        f += f" Tilauserä on {p.lot} {p.api_unit}."
        e += f" It is ordered in steps of {p.lot} {p.api_unit}."
    if p.catch_weight:
        f += " Laskutus todellisen painon mukaan."
        e += " It is invoiced by actual weight."
    return Msg(fi=f, en=e)


def make_offer(p: P, qty: int, need_date: date, ob: datetime, offer_set_id: str, tier: str) -> Offer:
    flags: list[OfferFlag] = []
    if p.logistics == "stock" and p.stock == "untracked":
        flags.append("STOCK_UNTRACKED")
    if p.net:
        flags.append("NET_PRICE")
    if p.variant:
        flags.append("VARIANT")
    if p.sales_unit != p.api_unit:
        flags.append("UNIT_MISMATCH")
    return Offer(
        offer_id=f"{offer_set_id}:{p.id}",
        tier=tier,
        product_id=p.id,
        name_fi=p.name,
        api_unit=p.api_unit,
        qty=qty,
        content_total=num(p.content * qty),
        unit_price_net=money(p.price),
        total_net=money(p.price * qty),
        price_per_base_unit=money(p.price / p.content),
        base_unit=p.base_unit,
        delivery_date=need_date.isoformat(),
        order_by=ob.isoformat(),
        stock=offer_stock(p),
        stock_qty=p.stock_qty if offer_stock(p) == "known" else None,
        flags=flags,
        explanation=explanation(p, qty, need_date, ob),
    )


def refusal(p: P, qty: int, need_date: date, ob: datetime | None, blocking: list[OfferFlag]) -> NotOffered:
    fi_parts, en_parts = [], []
    if "NOT_DELIVERABLE" in blocking:
        fi_parts.append("Ei toimitettavissa millekään päivälle.")
        en_parts.append("Cannot be delivered on any date.")
    if "CUTOFF_PASSED" in blocking and ob is not None:
        who_fi, who_en = ("Toimittajan", "supplier") if p.logistics == "terminal" else ("Valio Aimon", "Valio Aimo")
        fi_parts.append(f"{who_fi} tilausaika {day_fi(need_date)} toimitukseen päättyi {at_fi(ob)}.")
        en_parts.append(f"The {who_en} cut-off for delivery on {day_en(need_date)} passed on {at_en(ob)}.")
    if "OUT_OF_STOCK" in blocking:
        fi_parts.append("Loppu varastosta.")
        en_parts.append("Out of stock.")
    if "PARTIAL_STOCK" in blocking:
        fi_parts.append(f"Varastossa vain {p.stock_qty} × {p.api_unit}, tarvitaan {qty}.")
        en_parts.append(f"Only {p.stock_qty} × {p.api_unit} in stock; {qty} are needed.")
    flags = [*blocking, *(["UNIT_MISMATCH"] if p.sales_unit != p.api_unit else [])]
    return NotOffered(
        product_id=p.id, name_fi=p.name, flags=flags, reason=Msg(fi=" ".join(fi_parts), en=" ".join(en_parts))
    )


def _cutoff_note(cut: list[P]) -> tuple[str, str]:
    n = len(cut)
    if all(p.logistics == "terminal" for p in cut):
        if n == 1:
            return (
                "1 vaihtoehto tulee toimittajan varastosta, ja sen tilausaika on jo mennyt.",
                "1 option comes from a supplier warehouse and its cut-off has already passed.",
            )
        return (
            f"{n} vaihtoehtoa tulee toimittajan varastosta, ja niiden tilausaika on jo mennyt.",
            f"{n} options come from supplier warehouses and their cut-off has already passed.",
        )
    return (
        f"{n} vaihtoehdon tilausaika on jo mennyt.",
        f"The cut-off has already passed for {n} option{'s' if n > 1 else ''}.",
    )


def offers(req: OffersRequest, as_of: str) -> OffersResponse:
    """Options for one need: candidates by head and filters, then feasibility for need_date as of as_of (F-04)."""
    now = instant(as_of)
    need_date = date.fromisoformat(req.need_date)
    amount = Decimal(str(req.amount))
    offer_set_id = "OS-" + sha(req.model_dump_json())[:8].upper()
    heads = heads_for(req)
    rows = [p for p in matches(req, heads) if p.base_unit == req.unit and (req.allow_variants or not p.variant)]
    feasible: list[tuple[P, int, datetime]] = []
    refused: list[tuple[P, NotOffered, OfferFlag]] = []
    for p in rows:
        qty, ob, blocking = assess(p, amount, need_date, now)
        if blocking or ob is None:  # no order-by time means NOT_DELIVERABLE, which blocks
            refused.append((p, refusal(p, qty, need_date, ob, blocking), blocking[0]))
        else:
            feasible.append((p, qty, ob))
    options = [
        make_offer(p, qty, need_date, ob, offer_set_id, TIER_NAMES[i] if i < len(TIER_NAMES) else "other")
        for i, (p, qty, ob) in enumerate(feasible)
    ][: req.limit]
    counts = dict.fromkeys(COUNTS, 0) | {"candidates": len(rows), "on_time_full": len(feasible)}
    for _, _, primary in refused:
        counts[COUNT_KEY[primary]] += 1
    cut = [p for p, n, _ in refused if "CUTOFF_PASSED" in n.flags]

    fi_parts: list[str] = []
    en_parts: list[str] = []
    n_c = len(rows)
    found_fi = "1 sopivan tuotteen" if n_c == 1 else f"{n_c} sopivaa tuotetta"
    found_en = "1 matching product" if n_c == 1 else f"{n_c} matching products"
    if options:
        best = options[0]
        ob = datetime.fromisoformat(best.order_by)
        fi_parts += [
            f"Löysin {found_fi}; {len(feasible)} voidaan toimittaa {day_fi(need_date)} koko määrältä.",
            f"Paras ajoissa toimitettava vaihtoehto on {best.qty} × {quoted(best.name_fi)}, "
            f"{fi(best.total_net)} € alv 0 %, tilattava {at_fi(ob)} mennessä.",
        ]
        en_parts += [
            f"I found {found_en}; {len(feasible)} can deliver the full amount on {day_en(need_date)}.",
            f"The best on-time option is {best.qty} × {quoted(best.name_fi)}, EUR {best.total_net} excl. VAT, "
            f"to be ordered by {at_en(ob)}.",
        ]
        if "maito" in heads and any(w.endswith("maitojuoma") for w in words(best.name_fi)):
            fi_parts.append("Huomaa, että se on maitojuoma.")
            en_parts.append("Note that it is a milk drink (maitojuoma).")
    elif rows:
        fi_parts.append(f"Löysin {found_fi}, mutta yhtäkään ei voi toimittaa {day_fi(need_date)} koko määrältä.")
        en_parts.append(f"I found {found_en}, but none can deliver the full amount on {day_en(need_date)}.")
    else:
        fi_parts.append(f"En löytänyt luettelosta tuotetta, joka sopii tarpeeseen {quoted(req.query)}.")
        en_parts.append(f"I found no catalogue product that matches {quoted(req.query)}.")
    if cut:
        note = _cutoff_note(cut)
        fi_parts.append(note[0])
        en_parts.append(note[1])
    if not options and counts["partial"]:
        fi_parts.append(f"Varasto ei riitä koko määrään {counts['partial']} tuotteella.")
        en_parts.append(f"Stock does not cover the full amount for {counts['partial']} of them.")

    warnings = []
    if any("STOCK_UNTRACKED" in o.flags for o in options):
        warnings.append("Stock is not tracked for some options: shown as 'not tracked', not as a number.")
    if req.preference != "cheapest":
        warnings.append(f"stub: ranking by {req.preference} arrives with M5")
    warnings.append("stub: offers come from the stub catalogue until M5")
    warnings += invented_warnings([*(o.product_id for o in options), *(n.product_id for _, n, _ in refused)])
    return OffersResponse(
        offer_set_id=offer_set_id,
        need={
            "amount": req.amount,
            "unit": req.unit,
            "need_date": req.need_date,
            "claims": req.must_claims,
            "heads": heads,
            "exclude": req.exclude,
            "must_not_allergens": req.must_not_allergens,
            "temperature": req.temperature,
        },
        as_of=as_of,
        options=options,
        not_offered=[n for _, n, _ in refused],
        counts=counts,
        message_for_user=Msg(fi=" ".join(fi_parts), en=" ".join(en_parts)),
        warnings=warnings,
    )


def substitutes(req: SubstitutesRequest) -> SubstitutesResponse:
    p = PRODUCTS["464398"]  # a Valio Aimo stock row, so it always has an order-by time
    need_date = date.fromisoformat(req.need_date)
    ob = order_by(p, need_date) or helsinki_at(need_date - timedelta(days=1), "17:00")
    subs = [
        Substitute(
            product_id=p.id,
            name_fi=p.name,
            risk_tags=["needs_approval"],
            offer=make_offer(p, need_units(p, Decimal(str(req.amount))), need_date, ob, "OS-SUBST", "other"),
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
    """Offers, quotes, orders and approvals, in memory. Quotes are idempotent by (buyer, offer); the order and
    approval logic (PLAN M8, M9) is in orders.py, which keeps its records here."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.quotes: dict[str, Quote] = {}
        self.orders: dict[str, Order] = {}
        self.approvals: dict[str, Approval] = {}
        self.order_meta: dict[str, Any] = {}  # order_id -> orders.OrderMeta (owner, the quote as ordered, ...)
        self.idempotency: dict[str, tuple[str, str]] = {}  # key -> (payload fingerprint, order_id)
        self.seq = 0  # orders and approvals in the order they were made (newest first in the approver's list)
        self.offers: dict[str, Offer] = {}
        self.offer_sets: dict[str, OffersResponse] = {}
        self.offer_requests: dict[str, OffersRequest] = {}  # what each offer set was asked for ("Add to basket")
        self.audit: Any = None  # audit.AuditLog over the app's store, set by create_app (PLAN M10)

    def get_offers(self, req: OffersRequest, as_of: str) -> OffersResponse:
        res = offers(req, as_of)
        with self.lock:
            self.offers.update({o.offer_id: o for o in res.options})
            self.offer_sets[res.offer_set_id] = res
            self.offer_requests[res.offer_set_id] = req
        return res

    def get_offer_set(self, offer_set_id: str) -> OffersResponse | None:
        return self.offer_sets.get(offer_set_id)

    def offer_request(self, offer_set_id: str) -> OffersRequest | None:
        return self.offer_requests.get(offer_set_id)

    def price_product(
        self, product_id: str, amount: float, unit: str, need_date: str, as_of: str
    ) -> tuple[Offer | None, NotOffered | None]:
        """One row priced for one need: (the offer, None) when it can deliver in full, else (None, why not).

        (None, None) when the product is not in the catalogue or is not priced per `unit`. The offer is registered,
        so create_quote and a basket line can use its offer_id.
        """
        p = PRODUCTS.get(product_id)
        if p is None or p.base_unit != unit:
            return None, None
        d, amt = date.fromisoformat(need_date), Decimal(str(amount))
        qty, ob, blocking = assess(p, amt, d, instant(as_of))
        if blocking or ob is None:
            return None, refusal(p, qty, d, ob, blocking)
        offer_set_id = "OP-" + sha(f"{p.id}|{num(amt)}|{unit}|{need_date}")[:8].upper()  # one product, one need
        o = make_offer(p, qty, d, ob, offer_set_id, "other")
        with self.lock:
            self.offers[o.offer_id] = o
        return o, None

    def create_quote(self, buyer: Buyer, offer_id: str, as_of: str) -> QuoteResponse | None:
        o = self.offers.get(offer_id)
        p = PRODUCTS.get(o.product_id) if o else None
        if o is None or p is None:
            return None
        quote_id = "Q-" + sha(f"{buyer.buyer_id}|{offer_id}")[:10].upper()
        with self.lock:
            q = self.quotes.get(quote_id)
            if q is None:
                qty = o.qty
                line_net = p.price * qty
                line_vat = vat_of(line_net, p.vat)
                issued = datetime.fromisoformat(as_of)
                line = QuoteLine(
                    line_id=1,
                    product_id=p.id,
                    name_fi=p.name,
                    api_unit=p.api_unit,
                    qty=qty,
                    unit_price_net=money(p.price),
                    line_net=money(line_net),
                    vat_rate=str(p.vat),
                    line_vat=money(line_vat),
                    line_gross=money(line_net + line_vat),
                    delivery_date=o.delivery_date,
                )
                q = Quote(
                    quote_id=quote_id,
                    status="ready_for_complete",
                    buyer_id=buyer.buyer_id,
                    lines=[line],
                    total_net=money(line_net),
                    total_vat=money(line_vat),
                    total_gross=money(line_net + line_vat),
                    delivery_date=o.delivery_date,
                    issued_at=issued.isoformat(),
                    expires_at=quote_expiry(issued, [(p.id, o.delivery_date)]).isoformat(),
                    evidence=stub_evidence([line]),
                )
                q = sign_quote(q)
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
            warnings=invented_warnings([p.id]),
        )

    def create_basket_quote(self, buyer: Buyer, basket: Basket, as_of: str) -> Quote:
        """One fixed-price quote for every priced line of a basket, idempotent per (buyer, basket, version).

        Each line is priced as its basket line was: VAT per line on the net total at the row's rate, rounded
        half-up (F-06). Totals are the sums of the lines; delivery_date is the earliest line date; expires_at is
        the earliest of issue + 15 min, every line's order-by time and the end of each price's validTo day (F-07).
        The quote is signed (M6.3) and carries the snapshot it was priced from (M6.2).
        """
        priced = [line for line in basket.lines if line.status == "priced" and line.offer is not None]
        if not priced:
            raise ValueError("a basket quote needs at least one priced line")
        quote_id = "Q-" + sha(f"{buyer.buyer_id}|{basket.basket_id}|{basket.version}")[:10].upper()
        with self.lock:
            q = self.quotes.get(quote_id)
            if q is None:
                lines = []
                for line in priced:
                    o = line.offer
                    if o is None:
                        continue
                    unit_price = Decimal(o.unit_price_net)
                    net = unit_price * o.qty
                    rate = PRODUCTS[o.product_id].vat
                    vat = vat_of(net, rate)
                    lines.append(
                        QuoteLine(
                            line_id=line.line_id,
                            product_id=o.product_id,
                            name_fi=o.name_fi,
                            api_unit=o.api_unit,
                            qty=o.qty,
                            unit_price_net=money(unit_price),
                            line_net=money(net),
                            vat_rate=str(rate),
                            line_vat=money(vat),
                            line_gross=money(net + vat),
                            delivery_date=o.delivery_date,
                        )
                    )
                issued = instant(as_of)
                expires = min(
                    [
                        quote_expiry(issued, [(x.product_id, x.delivery_date) for x in lines]),
                        *(instant(x.offer.order_by) for x in priced if x.offer),
                    ]
                )
                q = Quote(
                    quote_id=quote_id,
                    status="ready_for_complete",
                    buyer_id=buyer.buyer_id,
                    lines=lines,
                    total_net=money(sum((Decimal(x.line_net) for x in lines), Decimal(0))),
                    total_vat=money(sum((Decimal(x.line_vat) for x in lines), Decimal(0))),
                    total_gross=money(sum((Decimal(x.line_gross) for x in lines), Decimal(0))),
                    delivery_date=min(x.delivery_date for x in lines),
                    basket_id=basket.basket_id,
                    basket_version=basket.version,
                    issued_at=issued.isoformat(),
                    expires_at=expires.isoformat(),
                    evidence=stub_evidence(lines),
                )
                q = sign_quote(q)
                self.quotes[quote_id] = q
        return q

    def get_quote(self, buyer: Buyer, quote_id: str) -> Quote | None:
        q = self.quotes.get(quote_id)
        return q if q is not None and q.buyer_id == buyer.buyer_id else None

    def confirm(self, buyer: Buyer, quote_id: str, now: str) -> ConfirmResponse | None:
        with self.lock:
            q = self.get_quote(buyer, quote_id)
            if q is None:
                return None
            if not q.confirmed and instant(q.expires_at) <= instant(now):  # an expired price cannot be confirmed
                return ConfirmResponse(
                    status="incomplete",
                    reason_code="quote_expired",
                    quote_id=quote_id,
                    confirmed=False,
                    message_for_user=Msg(
                        fi="Tarjouksen hinta ei ole enää voimassa. Tehdään uusi tarjous.",
                        en="The quote's fixed price has expired. Let's make a new quote.",
                    ),
                )
            if not q.confirmed:
                q = q.model_copy(update={"confirmed": True, "confirmed_at": now})
                self.quotes[quote_id] = q
        return ConfirmResponse(
            quote_id=quote_id,
            confirmed=True,
            confirmation_ref="C-" + quote_id[2:],
            message_for_user=Msg(fi="Vahvistettu.", en="Confirmed."),
        )
