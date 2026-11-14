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
from typing import Literal

from .contract import (
    Approval,
    ApprovalResponse,
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
from .fmt import CENT, UNIT_EN, UNIT_FI, at_en, at_fi, day_en, day_fi, fi, helsinki_at, instant, money, num, quoted
from .identity import Buyer

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
    """Offers, quotes and orders, in memory. Idempotent by (buyer, offer) and (conversation or buyer, quote)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.quotes: dict[str, Quote] = {}
        self.orders: dict[str, Order] = {}
        self.approvals: dict[str, Approval] = {}
        self.offers: dict[str, Offer] = {}
        self.offer_sets: dict[str, OffersResponse] = {}
        self.offer_requests: dict[str, OffersRequest] = {}  # what each offer set was asked for ("Add to basket")

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
                q = Quote(
                    quote_id=quote_id,
                    status="ready_for_complete",
                    buyer_id=buyer.buyer_id,
                    lines=[
                        QuoteLine(
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
                    ],
                    total_net=money(line_net),
                    total_vat=money(line_vat),
                    total_gross=money(line_net + line_vat),
                    delivery_date=o.delivery_date,
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
            warnings=["stub: quote is not signed yet (M6)", *invented_warnings([p.id])],
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
            order_id = "O-" + sha(idem)[:10].upper()
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
