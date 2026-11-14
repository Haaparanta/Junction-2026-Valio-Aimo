"""Offer comparison and good-better-best (PLAN M5): gates, signals, ranking, split plans and explanations.

A tiny catalog.db is built in the test with the M2 builder from hand-made records shaped like the W-03 milks, and the
Valio Aimo answers are hand-made entries in the shapes of A-02 and A-10, served by a fake client. No real data, no
fixtures and no network.
"""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from app.catalog import build, open_catalog
from app.clients.valio import ApiResult
from app.contract import OfferFlag, OffersRequest
from app.offers import (
    PROFILES,
    build_offer_set,
    consent_heads,
    estimate_reliability,
    get_offers,
    price_product,
    shortlist,
)
from app.search import Hit, SearchResult
from app.stubs import vat_of

SAT_10 = "2026-11-14T10:00:00+02:00"
SUN_1630 = "2026-11-15T16:30:00+02:00"
STOCK_SUN = "2026-11-15T17:00:00+0200"
TERMINAL_THU = "2026-11-12T15:00:00+0200"
LF = ("FREE_FROM_LACTOSE",)
CONTRACT_FLAGS = set(OfferFlag.__args__)


# ---- the tiny catalogue -------------------------------------------------------------------------


def product(pid, name_fi, *, vendor="VALIO OY TUORE", unit="ST", units=None, claims=LF, category="10400"):
    groups = [
        {"type": "ENUM", "name": "allergen", "values": [{"id": "AM", "unit": "CONTAINS"}]},
        {"type": "ENUM", "name": "nutritionalClaim", "values": [{"id": c, "unit": "FREE_FROM"} for c in claims]},
    ]
    return {
        "id": pid,
        "salesUnit": unit,
        "baseUnit": unit,
        "category": category,
        "allowedLotSize": 0.01,
        "deleted": False,
        "temperatureCondition": 4,
        "vendorName": vendor,
        "units": units or [{"unitId": unit, "sizeInBaseUnits": 1.0}],
        "deposits": [],
        "synkkaData": {
            "gtin": f"64000000{pid[:5]}",
            "names": [{"value": name_fi, "language": "fi"}],
            "classifications": groups,
        },
    }


CASE20 = [{"unitId": "ST", "sizeInBaseUnits": 1.0}, {"unitId": "KI", "sizeInBaseUnits": 20.0}]
MILKS = [
    product("464306", "Valio Arki Eila kevytmaitojuoma 1 l laktoositon", units=CASE20),
    product("464401", "Valio Arki Eila rasvaton maitojuoma 1 l laktoositon", units=CASE20),
    product("463335", "Valio Eila 3 % maitojuoma 1 l laktoositon"),
    product("464398", "Valio Eila kevytmaitojuoma 1 l UHT laktoositon"),
    product("464237", "Valio kahvimaito 1 l laktoositon UHT"),  # a variant (W-01)
    product("473142", "Valio kahvimaitojuoma vanilja 1 l laktoositon UHT"),  # flavoured: excluded (W-01)
    product("469119", "Valio Eila rasvaton maitojuoma 1,75 l laktoositon"),  # Terminal, cut-off passed (X-01)
    product("462626", "Valio kahvimaito 5 dl laktoositon"),  # Terminal and a variant
    product("469363", "Arla Kevytmaitojuoma 1 L UHT laktoositon", vendor="ARLA OY"),  # partial 384 (X-10)
    product("462775", "Arla Maitojuoma 1L laktoositon rasvaton UHT", vendor="ARLA OY"),  # partial 51 (X-10)
    product("464440", "Valio kevytmaito 0,5 l laktoositon UHT"),  # no schedule lines (X-07)
    product("463047", "Arla Täysmaito 1 L vähälaktoosinen UHT", vendor="ARLA OY", claims=("LOW_LACTOSE",)),  # X-24
    product("473625", "Laktoositon kondensoitu maito 400 g", vendor="DOVGAN"),  # sold by weight, need in litres
]
DRINKS = [  # same vendor and pack, different price and carbon: the greenest profile re-orders them
    product("470001", "Maito testijuoma 1 l", claims=(), category="10402"),
    product("470002", "Soija testijuoma 1 l", claims=(), category="10402"),
    product("470003", "Kaura testijuoma 1 l", claims=(), category="10402"),
    product("470004", "Riisi testijuoma 1 l", claims=(), category="10402"),
]
RELIABILITY = {"464306": 1.0, "464401": 1.0, "464398": 0.99, "464237": 1.0, "470001": 1.0, "470002": 1.0}
RELIABILITY |= {"470003": 1.0, "470004": 1.0}
CARBON = {"470001": 1.1, "470002": 0.6, "470003": 0.4, "470004": 0.9}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    d = tmp_path_factory.mktemp("offers")
    (d / "products.json").write_text(json.dumps(MILKS + DRINKS, ensure_ascii=False), encoding="utf-8")
    rel = "productId,deliveryReliability\n" + "".join(f"{k},{v}\n" for k, v in RELIABILITY.items())
    carb = "productId,AVG kg CO2-eq/kg\n" + "".join(
        f"{k},{CARBON.get(k, 1.1)}\n" for k in [p["id"] for p in MILKS + DRINKS]
    )
    (d / "rel.csv").write_text(rel, encoding="utf-8")
    (d / "carbon.csv").write_text(carb, encoding="utf-8")
    build(d / "products.json", d / "catalog.db", d / "rel.csv", d / "carbon.csv")
    c = open_catalog(d / "catalog.db")
    yield c
    c.close()


# ---- hand-made API answers (A-02, A-10) ---------------------------------------------------------


def stock(pid, amount=9999999999.0, unit="ST", closing=STOCK_SUN, model="Stock", day="2026-11-16", block=False):
    line = {"salesBlock": block, "availableAmount": amount, "salesUnit": unit}
    if day:
        line["availableDate"] = day
    return {
        "productId": pid,
        "closingTime": closing,
        "salesBlock": block,
        "logisticModel": model,
        "scheduleLines": [line],
    }


def terminal(pid, unit="ST"):
    return stock(pid, 999999.0, unit, TERMINAL_THU, "Terminal")


def window(value, to="9999-12-31T00:00:00+0200"):
    return {"value": value, "validFrom": "2026-01-01T00:00:00+0200", "validTo": to, "currency": "EUR"}


def price(pid, net, per_l=None, unit="L", lst=None, net_found=False, to="9999-12-31T00:00:00+0200"):
    return {
        "productId": pid,
        "quantity": 1.0,
        "catalogPrice": {**window(net, to), "valueWithTax": round(net * 1.135, 2)},
        "tax": {"taxRate": 13.5, "taxValue": 0.0},
        "listPrice": window(lst if lst is not None else round(net / 0.7, 2)),
        "netPriceFound": net_found,
        "comparisonPrice": window(per_l if per_l is not None else net),
        "comparisonUnit": unit,
        "error": False,
    }


AVAIL = {
    "464306": stock("464306"),
    "464401": stock("464401"),
    "463335": stock("463335"),
    "464398": stock("464398"),
    "464237": stock("464237"),
    "473142": stock("473142"),
    "469119": terminal("469119"),
    "462626": terminal("462626"),
    "469363": stock("469363", 384.0),
    "462775": stock("462775", 51.0),
    "464440": {"productId": "464440", "salesBlock": False, "scheduleLines": []},
    "473625": stock("473625"),
    **{p["id"]: stock(p["id"]) for p in DRINKS},
}
VALID_2026 = "2026-12-31T00:00:00+0200"
PRICES = {
    "464306": price("464306", 1.01, lst=1.44, net_found=True, to=VALID_2026),
    "464401": price("464401", 1.10, net_found=True, to=VALID_2026),
    "463335": price("463335", 1.40, net_found=True, to=VALID_2026),
    "464398": price("464398", 1.65),
    "464237": price("464237", 1.30),
    "473142": price("473142", 1.20),
    "469119": price("469119", 2.08, 1.19),
    "462626": price("462626", 1.30, 2.60),
    "469363": price("469363", 2.48),
    "462775": price("462775", 2.57),
    "464440": price("464440", 0.88, 1.76),
    "473625": price("473625", 2.40, 6.00, unit="KG"),
    "470001": price("470001", 1.00),
    "470002": price("470002", 1.25),
    "470003": price("470003", 1.50),
    "470004": price("470004", 1.02),
}


def api(endpoint, entries, ids, day):
    ids = list(dict.fromkeys(ids))
    found = {i: entries[i] for i in ids if i in entries}
    return ApiResult(
        endpoint=endpoint,
        customer="123",
        requested_date=str(day),
        entries=found,
        entry_evidence={i: f"{endpoint}-sha-{i}" for i in found},
        evidence=[],
        missing=[i for i in ids if i not in entries],
    )


class FakeClient:
    def __init__(self, avail=None, prices=None):
        self.avail = AVAIL if avail is None else avail
        self.prices = PRICES if prices is None else prices
        self.calls: list[tuple[str, list[str], str]] = []

    async def availability(self, ids, requested_date):
        ids = list(ids)
        self.calls.append(("availability", ids, str(requested_date)))
        return api("availability", self.avail, ids, requested_date)

    async def price(self, ids, requested_date):
        ids = list(ids)
        self.calls.append(("price", ids, str(requested_date)))
        return api("price", self.prices, ids, requested_date)


HEADLINE = {
    "query": "laktoositon maito",
    "heads": ["maito", "maitojuoma"],
    "must_claims": ["FREE_FROM_LACTOSE"],
    "amount": 1000,
    "unit": "L",
    "need_date": "2026-11-16",
}


async def offers_for(conn, client=None, as_of=SAT_10, **kw):
    req = OffersRequest(**{**HEADLINE, **kw})
    return await get_offers(req, conn=conn, client=client or FakeClient(), as_of=as_of)


def by_id(items):
    return {x.product_id: x for x in items}


# ---- 5.1: search, plan, price and availability, hard gates ---------------------------------------


async def test_headline_need_offers_open_stock_and_refuses_passed_terminal_cutoffs(conn):
    client = FakeClient()
    res = await offers_for(conn, client)
    r = res.response
    assert [(o.tier, o.product_id) for o in r.options] == [
        ("best", "464306"),
        ("better", "464401"),
        ("good", "463335"),
        ("other", "464398"),
    ]
    best = r.options[0]
    assert (best.qty, best.api_unit, best.total_net, best.price_per_base_unit) == (1000, "ST", "1010.00", "1.01")
    assert (best.content_total, best.stock, best.order_by) == ("1000", "untracked", "2026-11-15T17:00:00+02:00")
    assert set(best.flags) == {"STOCK_UNTRACKED", "NET_PRICE"}
    assert "VARIANT" not in {f for o in r.options for f in o.flags}  # coffee milk only with consent
    refused = by_id(r.not_offered)
    assert refused["469119"].flags == ["CUTOFF_PASSED"]
    assert set(refused["462626"].flags) == {"CUTOFF_PASSED", "VARIANT"}
    assert "VARIANT" in refused["464237"].flags
    assert refused["469363"].flags == ["PARTIAL_STOCK"] and refused["462775"].flags == ["PARTIAL_STOCK"]
    assert refused["464440"].flags == ["NOT_DELIVERABLE"]
    assert "cannot be compared" in refused["473625"].reason.en  # content in kg, need in litres
    c = r.counts
    assert (c["stock_full"], c["on_time_full"], c["offered"], c["variant_withheld"]) == (5, 5, 4, 1)
    assert (c["cutoff_passed"], c["cutoff_passed_terminal"], c["partial"], c["not_deliverable"]) == (2, 2, 2, 1)
    assert c["not_comparable"] == 1 and c["candidates"] == 11  # 13 milks less 463047 and 473142
    # Only the shortlisted ids are priced, once per endpoint, for the need date; low-lactose and the flavoured
    # coffee-milk drink never reach the API.
    assert [(e, d) for e, _, d in client.calls] == [("availability", "2026-11-16"), ("price", "2026-11-16")]
    asked = set(client.calls[0][1])
    assert asked == set(client.calls[1][1]) and "463047" not in asked and "473142" not in asked
    assert asked == {o.product_id for o in res.options}
    assert r.status == "ok" and r.reason_code is None


async def test_variants_are_offered_with_consent(conn):
    r = (await offers_for(conn, allow_variants=True)).response
    offered = by_id(r.options)
    assert "VARIANT" in offered["464237"].flags
    assert r.options[0].product_id == "464306"
    assert r.counts["variant_withheld"] == 0


def test_consent_heads_come_from_modifiers_that_are_also_variants():
    assert consent_heads(["maito", "maitojuoma"]) == ["kahvimaito", "kahvimaitojuoma"]
    assert consent_heads(["voi"]) == [] and consent_heads(["kahvimaito"]) == []


def test_shortlist_drops_flavoured_products_found_only_through_a_consent_head(conn):
    found = shortlist(conn, OffersRequest(**HEADLINE))
    assert "464237" in found.ids and "462626" in found.ids
    assert "473142" not in found.ids and found.interpretation["dropped"]["flavoured_variant"] == 1
    assert found.interpretation["consent_heads"] == ["kahvimaito", "kahvimaitojuoma"]


async def test_cutoff_inside_the_approval_buffer_is_refused(conn):
    r = (await offers_for(conn, as_of=SUN_1630)).response
    assert r.options == [] and r.reason_code == "cutoff_passed"
    best = by_id(r.not_offered)["464306"]
    assert best.flags[0] == "CUTOFF_PASSED"
    assert "leaves no time for approval" in best.reason.en and "Sun 15.11 16:00" in best.reason.en
    assert r.counts["cutoff_too_close"] >= 4


async def test_need_date_before_the_slot_is_late(conn):
    r = (await offers_for(conn, need_date="2026-11-15")).response
    assert r.options == []
    late = by_id(r.not_offered)["464306"]
    assert "NOT_DELIVERABLE" in late.flags and "1 day after the need date" in late.reason.en
    assert r.counts["late"] >= 4


async def test_price_not_valid_on_the_delivery_date_is_refused(conn):
    r = (await offers_for(conn, need_date="2027-01-04")).response  # X-16: validTo 31.12.2026
    refused = by_id(r.not_offered)
    assert "PRICE_NOT_VALID_FOR_DELIVERY_DATE" in refused["464306"].flags
    assert "valid to 31.12.2026" in refused["464306"].reason.en
    assert "464398" in by_id(r.options)  # no end date on its price: still offered, cut-off estimated (F-05)
    assert "estimated" in by_id(r.options)["464398"].explanation.en


async def test_blocked_out_of_stock_and_unpriced_rows_are_refused(conn):
    avail = {**AVAIL, "464401": stock("464401", block=True), "463335": stock("463335", 0.0, day=None)}
    prices = {**PRICES, "464398": {"productId": "464398", "quantity": 1.0, "netPriceFound": False, "error": True}}
    r = (await offers_for(conn, FakeClient(avail, prices))).response
    refused = by_id(r.not_offered)
    assert "SALES_BLOCKED" in refused["464401"].flags
    assert "OUT_OF_STOCK" in refused["463335"].flags
    assert refused["464398"].reason.en == "Valio Aimo returned no price."
    assert [o.product_id for o in r.options] == ["464306"]


async def test_nothing_found_calls_no_api(conn):
    client = FakeClient()
    r = (await get_offers(
        OffersRequest(query="olematon tuote", heads=["olematon"], amount=5, unit="KG", need_date="2026-11-16"),
        conn=conn, client=client, as_of=SAT_10,
    )).response  # fmt: skip
    assert r.options == [] and r.reason_code == "not_found" and client.calls == []
    assert '"olematon tuote"' in r.message_for_user.en


def test_diet_is_rechecked_on_the_record(conn):
    good = json.loads(conn.execute("SELECT record FROM products WHERE id='464306'").fetchone()[0])
    forged = {**good, "product_id": "469999", "claims": []}  # a hit that lost its lactose-free claim
    found = SearchResult(
        hits=[Hit("464306", good), Hit("469999", forged)],
        total_matches=2,
        mode="heads",
        interpretation={"heads": ["maitojuoma"], "must_claims": ["FREE_FROM_LACTOSE"], "banned_allergens": []},
    )
    req = OffersRequest(**HEADLINE)
    entries = {"469999": stock("469999"), "464306": AVAIL["464306"]}
    res = build_offer_set(
        req, found, api("availability", entries, ["464306", "469999"], "2026-11-16"),
        api("price", {**PRICES, "469999": price("469999", 0.10)}, ["464306", "469999"], "2026-11-16"), as_of=SAT_10,
    )  # fmt: skip
    assert [o.product_id for o in res.options] == ["464306"]
    assert any("469999 dropped" in w for w in res.response.warnings)


# ---- 5.2: signals, weights and deterministic re-ordering ----------------------------------------


def test_profiles_weigh_to_one():
    for w in PROFILES.values():
        assert sum(w.as_dict().values()) == pytest.approx(1.0)


def test_unknown_reliability_is_shrunk_towards_the_global_mean_and_capped():
    assert estimate_reliability(0, None) == 0.97  # global mean 0.972, capped
    assert estimate_reliability(200, 1.0) == 0.97  # a perfect category never makes an estimate perfect
    assert estimate_reliability(15, 0.509) == 0.774  # fresh beef 18720 (D-10) pulls the estimate down


async def test_estimated_reliability_is_labelled(conn):
    res = await offers_for(conn)
    whole = next(o for o in res.ranked if o.product_id == "463335")
    assert whole.reliability_estimated and whole.reliability == 0.97
    assert "Delivery reliability 0.97 (estimated)" in by_id(res.response.options)["463335"].explanation.en
    assert any("estimated" in w for w in res.response.warnings)
    assert res.as_dict()["ranking"][0]["reliability_source"] == "product_history"


DRINK_NEED = {"query": "testijuoma", "heads": ["testijuoma"], "amount": 100, "unit": "L", "need_date": "2026-11-16"}


async def test_greenest_reorders_deterministically(conn):
    async def order(pref):
        req = OffersRequest(**DRINK_NEED, preference=pref)
        res = await get_offers(req, conn=conn, client=FakeClient(), as_of=SAT_10)
        return res, [o.product_id for o in res.ranked]

    cheap, cheap_order = await order("cheapest")
    green, green_order = await order("greenest")
    again, again_order = await order("greenest")
    assert cheap_order[0] == "470001" and green_order[0] == "470003"
    assert green_order != cheap_order
    assert again_order == green_order and again.response == green.response  # same input, same answer
    assert green.profile == "green" and cheap.profile == "cost_saver"
    top = green.ranked[0]
    assert top.signals["carbon"] == 1.0 and top.contributions["carbon"] == pytest.approx(0.25)
    assert "lowest carbon" in top.tags and "lowest price" in cheap.ranked[0].tags


async def test_good_better_best_skips_near_duplicates(conn):
    # 470004 is the same vendor, model and pack as 470001 and only 2 % dearer: not a real alternative (R-05).
    r = (await get_offers(OffersRequest(**DRINK_NEED), conn=conn, client=FakeClient(), as_of=SAT_10)).response
    tiers = {o.product_id: o.tier for o in r.options}
    assert tiers["470001"] == "best" and tiers["470004"] == "other"
    assert tiers["470002"] == "better" and tiers["470003"] == "good"


# ---- 5.3: split plans (W-04, X-10) --------------------------------------------------------------


async def test_partial_stock_produces_a_split_proposal(conn):
    # Every full option is gone: only Arla's real stock (384 + 51 ST) is open (W-04 plan B).
    avail = {k: v for k, v in AVAIL.items() if k in ("469363", "462775", "469119")}
    res = await offers_for(conn, FakeClient(avail))
    r = res.response
    assert res.split is not None
    assert [(o.product_id, o.qty) for o in r.options] == [("469363", 384), ("462775", 51)]
    assert all("PARTIAL_STOCK" in o.flags and o.offer_id.endswith(f":split{i}") for i, o in enumerate(r.options, 1))
    assert (res.split.covered, res.split.shortfall) == (Decimal(435), Decimal(565))
    assert res.split.total_net == Decimal("952.32") + Decimal("131.07")  # 384 x 2.48 + 51 x 2.57 (W-04: 1,083.39)
    assert (
        "Split proposal over 2 products" in r.message_for_user.en and "565 L remain uncovered" in r.message_for_user.en
    )
    assert "SPLIT 1/2" in r.options[0].explanation.en and "A firm line." in r.options[0].explanation.en
    assert "469363" not in by_id(r.not_offered)


async def test_split_when_rank_one_is_exact_stock_short_of_the_need(conn):
    # 990 ST of the cheapest milk in real stock ranks first; the rest comes from the next option (R-05).
    avail = {"464306": stock("464306", 990.0), "464398": stock("464398")}
    res = await offers_for(conn, FakeClient(avail))
    assert res.ranked[0].product_id == "464306" and res.ranked[0].gate == "partial"
    assert [(ln.product_id, ln.qty) for ln in res.split.lines] == [("464306", 990), ("464398", 10)]
    assert res.split.shortfall == 0 and res.split.covered == 1000
    r = res.response
    assert r.options[0].tier == "best" and r.options[0].product_id == "464398"  # the only full option
    assert [o.offer_id.rsplit(":", 1)[-1] for o in r.options[1:]] == ["split1", "split2"]


# ---- 5.4: explanations with live numbers (R-06, W-05) -------------------------------------------


async def test_explanations_carry_the_live_numbers_in_both_languages(conn):
    r = (await offers_for(conn)).response
    best = r.options[0]
    en, fi = best.explanation.en, best.explanation.fi
    gross = Decimal(best.total_net) + vat_of(Decimal(best.total_net), Decimal("13.5"))  # what the quote computes
    assert gross == Decimal("1146.35")
    for part in (
        "BEST (lowest price, meets all must-haves)",
        "[464306], VALIO OY TUORE",
        "1,000 × ST = 1,000 L (= 50 × KI of 20)",
        "EUR 1,010.00 excl. VAT (EUR 1,146.35 incl. 13.5 % VAT), 1.01 EUR/L",
        "customer price valid to 31.12.2026",
        "Delivery Mon 16.11 from Valio Aimo stock, quantity not tracked; order by Sun 15.11 17:00 (31.0 h left)",
        "Delivery reliability 1.00 (product history)",
        "Carbon about 1.1 kg CO2e/kg (category average), about 1,100 kg CO2e",
        "Why first: cheapest of the 4 options that can deliver the full 1,000 L on Mon 16.11.",
        "Approve before Sun 15.11 16:00.",
    ):
        assert part in en, part
    for part in (
        "PARAS (edullisin, täyttää kaikki vaatimukset)",
        "1 000 × ST = 1 000 l",
        "1 010,00 € alv 0 % (1 146,35 € sis. alv 13,5 %), 1,01 €/l",
        "asiakashinta voimassa 31.12.2026 asti",
        "tilattava viimeistään su 15.11. klo 17.00 (31,0 h aikaa)",
        "Hyväksyttävä viimeistään su 15.11. klo 16.00.",
    ):
        assert part in fi, part
    assert ".." not in fi and ".." not in en
    better = r.options[1].explanation.en
    assert "BETTER" in better and "Trade-off vs BEST: +EUR 90.00; same stock status, cut-off and reliability." in better
    cut = by_id(r.not_offered)["469119"].reason
    assert "The supplier cut-off for delivery on Mon 16.11 passed on Thu 12.11 15:00" in cut.en
    assert "Toimittajan tilausaika toimitukseen ma 16.11. päättyi to 12.11. klo 15.00" in cut.fi
    msg = r.message_for_user
    assert "5 can deliver the full 1,000 L on Mon 16.11 (1 of them a variant you have not accepted)" in msg.en
    assert "2 options come from supplier warehouses and their cut-off has already passed" in msg.en
    assert msg.fi and msg.en


async def test_unit_mismatch_and_rounding_are_explained(conn):
    # The API sells 464401 per KI of 20 (A-08): 1,000 L is 50 KI, and the explanation says so.
    avail = {"464401": stock("464401", unit="KI")}
    prices = {"464401": price("464401", 22.00, 1.10)}
    r = (await offers_for(conn, FakeClient(avail, prices), amount=990)).response
    o = r.options[0]
    assert (o.api_unit, o.qty, o.total_net, o.content_total) == ("KI", 50, "1100.00", "1000")
    assert "UNIT_MISMATCH" in o.flags
    assert "The API sells this per KI (20 L each), not per ST as in the catalogue" in o.explanation.en
    assert "rounding up to whole units gives 10 L more than needed (1 %)" in o.explanation.en


async def test_response_is_contract_shaped_and_serialisable(conn):
    res = await offers_for(conn)
    for o in res.response.options:
        assert set(o.flags) <= CONTRACT_FLAGS
        assert o.offer_id.startswith(res.response.offer_set_id + ":")
    doc = json.loads(json.dumps(res.as_dict()))
    assert doc["profile"] == "cost_saver" and doc["ranking"][0]["band"] == "A"
    assert doc["ranking"][0]["evidence"] == ["availability-sha-464306", "price-sha-464306"]
    assert set(doc["weights"]) == {"price", "delivery", "availability", "reliability", "preference", "carbon"}
    assert res.response.as_of == "2026-11-14T10:00:00+02:00"


async def test_offer_set_id_is_stable_and_follows_the_clock(conn):
    a = (await offers_for(conn)).response.offer_set_id
    b = (await offers_for(conn)).response.offer_set_id
    c = (await offers_for(conn, as_of="2026-11-14T11:00:00+02:00")).response.offer_set_id
    assert a == b != c


async def test_custom_buffer_moves_the_approval_deadline(conn):
    req = OffersRequest(**HEADLINE)
    res = await get_offers(req, conn=conn, client=FakeClient(), as_of=SAT_10, buffer=timedelta(hours=3))
    assert "Approve before Sun 15.11 14:00." in res.response.options[0].explanation.en


# ---- price_product: one product for one need ----------------------------------------------------


async def test_price_product_mirrors_the_stub_contract(conn):
    client = FakeClient()
    kw = {"conn": conn, "client": client, "as_of": SAT_10}
    offer, why = await price_product("464306", 1000, "L", "2026-11-16", **kw)
    assert why is None and offer.offer_id.startswith("OP-") and (offer.qty, offer.total_net) == (1000, "1010.00")
    offer, why = await price_product("469119", 1000, "L", "2026-11-16", **kw)
    assert offer is None and why.flags == ["CUTOFF_PASSED"]
    offer, why = await price_product("464237", 10, "L", "2026-11-16", heads=["maito"], **kw)  # chosen variant
    assert why is None and "VARIANT" in offer.flags
    offer, why = await price_product("469363", 1000, "L", "2026-11-16", **kw)
    assert offer is None and why.flags == ["PARTIAL_STOCK"]  # no split for a pinned product
    assert await price_product("999999", 1, "L", "2026-11-16", **kw) == (None, None)  # not in the catalogue
    assert await price_product("473625", 1, "L", "2026-11-16", **kw) == (None, None)  # sold by weight
