"""The stub catalogue and offers() (docs/basket-plan.md B-10, M22.1): candidates by head, filters, cut-offs."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from app.contract import OffersRequest, PlanQuantityRequest, SearchRequest
from app.fmt import at_en, at_fi, day_en, day_fi, helsinki_at, instant, to_helsinki
from app.stubs import PRODUCTS, StubState, assess, get_product, offers, plan_quantity, search
from conftest import voice_headers

AS_OF = "2026-11-14T10:00:00+02:00"  # Sat 14.11 10:00, the demo clock
BUTTER = {"464076", "463233"}


def need(**kw) -> OffersRequest:
    return OffersRequest(**({"amount": 10, "unit": "KG", "need_date": "2026-11-16"} | kw))


def shown(res) -> set[str]:
    return {o.product_id for o in res.options} | {n.product_id for n in res.not_offered}


def test_butter_gives_only_butter():
    res = offers(need(query="voi", heads=["voi"], amount=20, allow_variants=True), AS_OF)
    assert shown(res) == BUTTER
    best = res.options[0]
    assert (best.product_id, best.qty, best.total_net, best.tier) == ("464076", 4, "149.32", "best")  # 4 x 5 kg
    assert res.options[1].flags == ["STOCK_UNTRACKED", "VARIANT"]  # 10 g portions only with consent


def test_variants_are_dropped_without_consent():
    res = offers(need(query="voi", heads=["voi"], amount=20), AS_OF)
    assert shown(res) == {"464076"} and res.counts["candidates"] == 1


def test_english_query_maps_to_the_finnish_head():
    assert shown(offers(need(query="20 kg butter"), AS_OF)) == {"464076"}
    assert offers(need(query="frozen strawberries"), AS_OF).need["heads"] == ["mansikka"]


def test_an_empty_head_never_matches_everything():
    res = offers(need(query="voi", heads=["", "  "]), AS_OF)
    assert shown(res) == {"464076"}  # falls back to the query's last word


def test_exclude_words_drop_rows():
    both = offers(need(query="sokeri", heads=["sokeri"], amount=1), AS_OF)
    assert shown(both) == {"468904", "468911"}
    res = offers(need(query="sokeri", heads=["sokeri", "taloussokeri"], exclude=["tomusokeri"], amount=1), AS_OF)
    assert shown(res) == {"468904"}


def test_lactose_free_cream_excludes_other_cream():
    cream = {"query": "laktoositon kerma", "heads": ["kerma", "kuohukerma", "vispikerma"], "unit": "L"}
    every = offers(need(**cream), AS_OF)
    assert {"467318", "461755"} <= shown(every)  # plain cream and a minimal record without claims
    res = offers(need(**cream, must_claims=["FREE_FROM_LACTOSE"]), AS_OF)
    assert shown(res) == {"467310", "469346"}
    assert all("FREE_FROM_LACTOSE" in PRODUCTS[i].claims for i in shown(res))


def test_unknown_allergen_data_is_never_safe():
    base = {"query": "kerma", "heads": ["kerma"], "unit": "L", "amount": 5}
    assert "461755" in shown(offers(need(**base), AS_OF))
    res = offers(need(**base, must_not_allergens=["AE"]), AS_OF)
    assert "461755" not in shown(res)  # no allergen data: excluded although it declares nothing
    assert {"467310", "467318", "469346"} <= shown(res)  # declared without eggs: kept
    assert shown(offers(need(**base, must_not_allergens=["AM"]), AS_OF)) == set()  # all dairy contains milk


def test_gluten_free_flour_mix():
    res = offers(
        need(
            query="gluteeniton jauhoseos",
            heads=["jauhoseos"],
            must_claims=["FREE_FROM_GLUTEN"],
            must_not_allergens=["AW", "UW", "GB", "NR", "GO"],
            amount=1,
        ),
        AS_OF,
    )
    assert shown(res) == {"473305"}
    assert "AW" in PRODUCTS["470212"].allergens and "UW" in PRODUCTS["470212"].allergens  # wheat flour


def test_temperature_filter():
    frozen = offers(need(query="mansikka", heads=["mansikka"], temperature="frozen", amount=3), AS_OF)
    assert shown(frozen) == {"466932"} and frozen.options[0].qty == 2  # 2 x 2.5 kg
    fresh = offers(need(query="tuoreet mansikat", heads=["mansikka"], temperature="chilled", amount=3), AS_OF)
    assert shown(fresh) == {"471820"} and fresh.options[0].qty == 2  # 2 x 2 kg of fresh strawberries
    # An unknown temperature class is not a mismatch (D-08): eggs (code 6) stay in a chilled search.
    eggs = need(query="kananmuna", heads=["kananmuna"], temperature="chilled", amount=120, unit="PCS")
    assert shown(offers(eggs, AS_OF)) == {"472535"}


def test_a_strawberry_cake_finds_fresh_strawberries_and_jam():
    """A mansikkakakku plan asks for 'tuoreet mansikat' and 'mansikkahillo'; both are invented stub rows."""
    fresh = offers(need(query="tuoreet mansikat", heads=["mansikka"], temperature="chilled", amount=4), AS_OF)
    assert [o.product_id for o in fresh.options] == ["471820"]
    jam = offers(need(query="mansikkahillo", heads=["hillo", "mansikkahillo"], amount=2), AS_OF)
    assert [o.product_id for o in jam.options] == ["471837"] and jam.options[0].qty == 1  # 1 x 3 kg
    assert "stub: invented catalogue values for 471837" in jam.warnings


def test_unit_must_match_the_base_unit():
    assert shown(offers(need(query="voi", heads=["voi"], unit="L"), AS_OF)) == set()
    eggs = offers(need(query="kananmuna", heads=["kananmuna"], amount=120, unit="PCS"), AS_OF).options[0]
    assert (eggs.qty, eggs.api_unit, eggs.content_total, eggs.total_net) == (2, "KI", "180", "37.80")


@pytest.mark.parametrize(
    ("need_date", "butter_order_by", "terminal_flags"),
    [
        ("2026-11-14", None, ["CUTOFF_PASSED", "UNIT_MISMATCH"]),  # stock closed Fri 13.11 17:00
        ("2026-11-16", "2026-11-15T17:00:00+02:00", ["CUTOFF_PASSED", "UNIT_MISMATCH"]),  # terminal Thu 12.11 15:00
        ("2026-11-17", "2026-11-16T17:00:00+02:00", ["CUTOFF_PASSED", "UNIT_MISMATCH"]),  # terminal Fri 13.11 15:00
        ("2026-11-18", "2026-11-17T17:00:00+02:00", None),  # terminal Sat 14.11 15:00 is still open at 10:00
    ],
)
def test_cutoff_math_as_of_saturday_morning(need_date, butter_order_by, terminal_flags):
    butter = offers(need(query="voi", heads=["voi"], need_date=need_date), AS_OF)
    if butter_order_by is None:
        assert butter.options == [] and butter.not_offered[0].flags == ["CUTOFF_PASSED"]
        assert "pe 13.11. klo 17.00" in butter.not_offered[0].reason.fi
    else:
        assert butter.options[0].order_by == butter_order_by
        assert butter.options[0].delivery_date == need_date
    milk = offers(need(query="kevytmaito", heads=["kevytmaito"], unit="L", amount=30, need_date=need_date), AS_OF)
    arla = {o.product_id: o for o in milk.options}.get("465244")
    if terminal_flags is None:
        assert arla is not None and arla.flags == ["UNIT_MISMATCH"] and arla.qty == 10  # KI = 3.0 L (X-14)
        assert arla.order_by == "2026-11-14T15:00:00+02:00" and arla.stock == "unknown_terminal"
    else:
        assert arla is None
        assert {n.product_id: n.flags for n in milk.not_offered}["465244"] == terminal_flags


def test_not_deliverable_and_partial_stock():
    smetana = offers(need(query="smetana", heads=["smetana"], amount=1), AS_OF)
    assert smetana.options == [] and smetana.not_offered[0].flags == ["NOT_DELIVERABLE"]
    assert smetana.counts["not_deliverable"] == 1
    cream = offers(
        need(query="kerma", heads=["kuohukerma"], must_claims=["FREE_FROM_LACTOSE"], unit="L", amount=50), AS_OF
    )
    partial = {n.product_id: n for n in cream.not_offered}["469346"]
    assert partial.flags == ["PARTIAL_STOCK"] and "48" in partial.reason.en  # 48 ST for a 50 L need (X-10)
    lf40 = need(
        query="kerma", heads=["kuohukerma", "vispikerma"], must_claims=["FREE_FROM_LACTOSE"], unit="L", amount=40
    )
    assert offers(lf40, AS_OF).options[0].product_id == "469346"  # 48 in stock covers 40


def test_zero_stock_is_out_of_stock():
    p = replace(PRODUCTS["464076"], stock="none")
    qty, order_by, flags = assess(p, Decimal(20), date(2026, 11, 16), instant(AS_OF))
    assert (qty, order_by.isoformat(), flags) == (4, "2026-11-15T17:00:00+02:00", ["OUT_OF_STOCK"])


def test_catch_weight_lot_and_vendor_cutoff():
    steak = offers(need(query="flank steak", amount=25, need_date="2026-11-18", temperature="frozen"), AS_OF)
    o = steak.options[0]
    assert (o.product_id, o.qty, o.total_net) == ("460675", 30, "875.10")  # lot 10 KG at 29.17 (X-15)
    assert o.order_by == "2026-11-14T13:00:00+02:00"  # the vendor's 13:00, not the default 15:00
    assert "actual weight" in o.explanation.en
    monday = offers(need(query="flank steak", amount=25), AS_OF)
    assert monday.not_offered[0].flags == ["CUTOFF_PASSED"] and "to 12.11. klo 13.00" in monday.not_offered[0].reason.fi


def test_potato_prices_per_kg_are_the_recorded_ones():
    res = offers(need(query="potatoes", amount=50), AS_OF)
    assert [(o.product_id, o.price_per_base_unit) for o in res.options] == [("470961", "0.65"), ("460603", "3.62")]


def test_explanations_use_helsinki_dates():
    o = offers(need(query="voi", heads=["voi"], amount=20), AS_OF).options[0]
    assert "ma 16.11." in o.explanation.fi and "su 15.11. klo 17.00" in o.explanation.fi
    assert "Mon 16.11" in o.explanation.en and "Sun 15.11 17:00" in o.explanation.en
    assert "149,32 €" in o.explanation.fi and "EUR 149.32" in o.explanation.en


def test_w03_message_keeps_the_demo_notes():
    w03 = need(
        query="laktoositon maito",
        heads=["maito", "maitojuoma"],
        must_claims=["FREE_FROM_LACTOSE"],
        amount=1000,
        unit="L",
    )
    res = offers(w03, AS_OF)
    assert "maitojuoma" in res.message_for_user.fi and "milk drink" in res.message_for_user.en
    assert (
        "toimittajan varastosta" in res.message_for_user.fi and "cut-off has already passed" in res.message_for_user.en
    )
    assert "1010,00 €" in res.message_for_user.fi and "EUR 1010.00" in res.message_for_user.en
    assert res.counts == {
        "candidates": 12,
        "on_time_full": 7,
        "partial": 1,
        "cutoff_passed": 3,
        "not_deliverable": 1,
        "out_of_stock": 0,
    }
    assert sum(res.counts.values()) - res.counts["candidates"] == res.counts["candidates"]
    assert not [w for w in res.warnings if "invented" in w]  # the W-03 milks are recorded values
    # Asked for maitojuoma only, the note does not apply.
    drink_only = offers(w03.model_copy(update={"heads": ["maitojuoma"]}), AS_OF)
    assert "Huomaa" not in drink_only.message_for_user.fi and "milk drink" not in drink_only.message_for_user.en


def test_invented_rows_are_flagged_in_warnings():
    res = offers(need(query="sokeri", heads=["sokeri"], amount=1), AS_OF)
    assert "stub: invented catalogue values for 468904" in res.warnings
    assert "stub: invented catalogue values for 468911" in res.warnings
    assert "stub: invented catalogue values for 469338" in get_product("469338").warnings
    assert "stub: invented catalogue values for 464322" in search(SearchRequest(query="kahvi")).warnings


def test_preference_keeps_the_order_and_says_so():
    cheap = offers(need(query="kahvi", heads=["kahvi"], amount=12), AS_OF)
    green = offers(need(query="kahvi", heads=["kahvi"], amount=12, preference="greenest"), AS_OF)
    assert [o.product_id for o in green.options] == [o.product_id for o in cheap.options] == ["470153", "464322"]
    assert "stub: ranking by greenest arrives with M5" in green.warnings


def test_offer_set_id_is_deterministic_from_the_full_request():
    a = offers(need(query="voi", heads=["voi"]), AS_OF).offer_set_id
    assert a == offers(need(query="voi", heads=["voi"]), AS_OF).offer_set_id
    assert a != offers(need(query="voi", heads=["voi"], exclude=["kirnu"]), AS_OF).offer_set_id


def test_search_uses_the_same_filter():
    res = search(SearchRequest(query="butter"))
    assert {p.product_id for p in res.products} == BUTTER and res.total_matches == 2
    milk = search(SearchRequest(query="maito", heads=["maito", "maitojuoma"], must_claims=["FREE_FROM_LACTOSE"]))
    assert milk.total_matches == 13 and len(milk.products) == 10  # limit 10
    assert all(p.claims == ["FREE_FROM_LACTOSE"] for p in milk.products)


def test_product_record_uses_the_row():
    p = get_product("465244").product
    assert (p.sales_unit, p.content_per_unit.value, p.content_per_unit.unit) == ("ST", "0.5", "L")  # catalogue unit
    assert (p.claims, p.allergens_contains, p.brand, p.category) == ([], ["AM"], "Arla", "10400")
    flour = get_product("473305")
    assert flour.product.claims == ["FREE_FROM_GLUTEN"] and flour.product.temperature_class == "ambient"
    assert flour.json_ld["gs1:nutritionalClaim"] == "gs1:NutritionalClaimTypeCode-FREE_FROM_GLUTEN"
    assert "brand" not in get_product("461755").json_ld  # a minimal record has no brand


def test_plan_quantity_for_kg_and_pieces():
    eggs = plan_quantity(PlanQuantityRequest(product_id="472535", amount=120, unit="PCS"))
    assert (eggs.units_needed, eggs.total_content, eggs.overshoot) == (2, "180", "60") and "stub" in eggs.warnings
    butter = plan_quantity(PlanQuantityRequest(product_id="463233", amount=10, unit="KG"))
    assert (butter.units_needed, butter.total_content, butter.overshoot) == (5, "10.5", "0.5")  # KI = 2.1 kg (X-21)
    wrong = plan_quantity(PlanQuantityRequest(product_id="464076", amount=10, unit="L"))
    assert wrong.units_needed == 0 and "KG" in wrong.message_for_user.en


def test_price_product_registers_the_offer():
    stubs = StubState()
    o, refused = stubs.price_product("464076", 20, "KG", "2026-11-16", AS_OF)
    assert refused is None and o is not None and stubs.offers[o.offer_id] == o and o.total_net == "149.32"
    o2, refused = stubs.price_product("464076", 20, "KG", "2026-11-14", AS_OF)
    assert o2 is None and refused.flags == ["CUTOFF_PASSED"]
    assert stubs.price_product("464076", 20, "L", "2026-11-16", AS_OF) == (None, None)  # wrong unit
    assert stubs.price_product("999999", 20, "KG", "2026-11-16", AS_OF) == (None, None)  # not in the catalogue


def test_offer_requests_are_kept_per_offer_set():
    stubs = StubState()
    req = need(query="voi", heads=["voi"])
    res = stubs.get_offers(req, AS_OF)
    assert stubs.offer_requests[res.offer_set_id] == req


def test_get_offers_refuses_a_date_that_does_not_exist(chef):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    body = {"query": "voi", "heads": ["voi"], "amount": 20, "unit": "KG", "need_date": "2026-02-30"}
    assert chef.post("/v1/offers", json=body, headers=voice_headers(s)).status_code == 422


def test_helsinki_offsets_and_formats():
    assert helsinki_at(date(2026, 11, 15), "17:00").isoformat() == "2026-11-15T17:00:00+02:00"
    assert helsinki_at(date(2026, 6, 15), "17:00").isoformat() == "2026-06-15T17:00:00+03:00"  # summer time
    assert helsinki_at(date(2026, 3, 29), "15:00").utcoffset().total_seconds() == 3 * 3600  # last Sunday of March
    assert helsinki_at(date(2026, 10, 25), "15:00").utcoffset().total_seconds() == 2 * 3600  # last Sunday of October
    t = datetime.fromisoformat("2026-11-15T15:00:00+00:00")
    assert (at_fi(t), at_en(t)) == ("su 15.11. klo 17.00", "Sun 15.11 17:00")
    assert (day_fi(date(2026, 11, 16)), day_en(date(2026, 11, 16))) == ("ma 16.11.", "Mon 16.11")
    assert to_helsinki(instant("2026-11-14T10:00:00")).isoformat() == "2026-11-14T10:00:00+02:00"
