"""plan_quantity and the F-01 content vote (PLAN M3.5): units, lot-size rounding, overshoot and warnings.

Catalogue facts and prices are the observed values of the cited ids (docs/data-and-api-findings.md D-06, F-01, F-02,
X-13, X-14, X-21, X-23). The static content stands in for what the catalogue build (M2) provides.
"""

from decimal import Decimal

import pytest
from app.quantity import CatalogUnits, StaticContent, api_content, plan_quantity, vote_content


def price(net, comp=None, unit="L"):
    entry = {"productId": "x", "catalogPrice": {"value": net}, "error": False}
    if comp is not None:
        entry["comparisonPrice"] = {"value": comp}
        entry["comparisonUnit"] = unit
    return entry


def static(value, dim, per_unit, source="unit_conversions", confidence="high"):
    return StaticContent(value=Decimal(str(value)), dim=dim, per_unit=per_unit, source=source, confidence=confidence)


MILK_464306 = CatalogUnits(
    product_id="464306",
    sales_unit="ST",
    base_unit="ST",
    units={"KRS": 160, "PAL": 160, "KI": 20, "ST": 1},
    static_content=[static(1.0, "L", "ST"), static(1, "L", "ST", "name", "medium")],
)
ARLA_465244 = CatalogUnits(
    product_id="465244",
    sales_unit="ST",
    base_unit="ST",
    units={"KI": 6, "ST": 1},
    static_content=[static(0.5, "L", "ST")],
)
BUTTER_463233 = CatalogUnits(product_id="463233", sales_unit="KI", base_unit="KI", units={"KI": 1})
KALINKA_476738 = CatalogUnits(
    product_id="476738",
    sales_unit="ST",
    base_unit="ST",
    units={"KRS": 200, "KI": 20, "ST": 1},
    static_content=[static(0.15, "KG", "ST"), static(0.15, "KG", "ST", "name", "medium")],
)


def test_headline_1000_litres_of_464306():
    plan = plan_quantity(
        1000, "L", catalog=MILK_464306, api_unit="ST", price_entry=price(1.01, 1.01), stock_kind="untracked"
    )
    assert plan.qty == 1000 and plan.content.value == 1 and plan.content.source == "vote"
    assert plan.total_content == 1000 and plan.overshoot == 0 and plan.overshoot_pct == 0
    assert plan.total_net == Decimal("1010.00") and plan.price_per_content == Decimal("1.01")
    assert plan.orderable_qty == 1000 and plan.max_orderable is None  # untracked stock caps nothing
    assert plan.case_alternative.model_dump() == {
        "unit": "KI", "cases": 50, "api_units_per_case": 20, "qty": 1000, "exact": True,
    }  # fmt: skip
    assert plan.flags == [] and plan.warnings == []


def test_465244_converts_through_ki_of_3_litres():
    """X-14: the API sells 465244 per KI (6 x 0.5 L); 6.22 / 2.07 = 3.005 snaps to the static 3.0."""
    plan = plan_quantity(
        1000,
        "L",
        catalog=ARLA_465244,
        availability_entry={"scheduleLines": [{"salesUnit": "KI", "availableAmount": 999999.0}]},
        price_entry=price(6.22, 2.07),
    )
    assert plan.api_unit == "KI" and plan.catalog_unit == "ST"
    assert plan.content.value == Decimal("3") and plan.content.agreeing == ["api", "unit_conversions"]
    assert plan.qty == 334 and plan.total_content == 1002 and plan.overshoot_pct == Decimal("0.2")
    assert "UNIT_MISMATCH" in plan.flags
    assert any("sells this in KI" in w for w in plan.warnings)


def test_463233_gives_2_1_kg_per_ki():
    """X-21: the name says 10 g, the API says 2.1 kg per case; name-only would under-order about 200 times."""
    alone = plan_quantity(500, "KG", catalog=BUTTER_463233, api_unit="KI", price_entry=price(23.42, 11.15, "KG"))
    assert alone.content.value == Decimal("2.1") and alone.content.source == "api"
    assert alone.content.needs_review and "CONTENT_UNCONFIRMED" in alone.flags
    assert alone.qty == 239  # 500 / 2.1 = 238.1

    with_name = BUTTER_463233.model_copy(update={"static_content": [static(0.01, "KG", "KI", "name", "low")]})
    voted = plan_quantity(500, "KG", catalog=with_name, api_unit="KI", price_entry=price(23.42, 11.15, "KG"))
    assert voted.content.value == Decimal("2.1")
    assert {"CONTENT_CONFLICT", "NEEDS_REVIEW"} <= set(voted.flags)
    assert voted.content.disagreeing == ["name"]


def test_476738_is_a_conflict_resolved_by_the_vote():
    """X-23: 0.91 EUR at 0.30 EUR/kg implies 3.03 kg; unit conversions and the name say 150 g."""
    vote = vote_content("ST", KALINKA_476738, price(0.91, 0.30, "KG"), dim="KG")
    assert vote.value == Decimal("0.15") and vote.source == "vote" and not vote.needs_review
    assert "CONTENT_CONFLICT" in vote.flags and vote.disagreeing == ["api"]
    plan = plan_quantity(3, "KG", catalog=KALINKA_476738, api_unit="ST", price_entry=price(0.91, 0.30, "KG"))
    assert plan.qty == 20 and "CONTENT_CONFLICT" in plan.flags
    assert plan.price_per_content == Decimal("6.07")  # per voted kg, not the API's misleading 0.30 (F-09)
    assert any("api says 3.033 KG per ST" in w for w in plan.warnings)


def test_464076_vote_overrules_wrong_product_data():
    """D-06: unit conversions say 20 kg, the name and the price say 5 kg per ST."""
    eila = CatalogUnits(
        product_id="464076", sales_unit="ST", base_unit="ST", units={"PAL": 160, "KI": 4, "ST": 1},
        static_content=[static(20, "KG", "ST"), static(5, "KG", "ST", "name", "medium")],
    )  # fmt: skip
    vote = vote_content("ST", eila, price(37.33, 7.47, "KG"), dim="KG")
    assert vote.value == Decimal("5") and vote.disagreeing == ["unit_conversions"]


def test_cent_rounding_snaps_to_the_static_value():
    """F-01: 469119 2.08 / 1.19 = 1.748 L, really 1.75 L; 1,000 L gives 572 ST."""
    bottle = CatalogUnits(
        product_id="469119", sales_unit="ST", base_unit="ST", static_content=[static(1.75, "L", "ST")]
    )
    plan = plan_quantity(1000, "L", catalog=bottle, api_unit="ST", price_entry=price(2.08, 1.19))
    assert plan.content.value == Decimal("1.75") and plan.qty == 572


@pytest.mark.parametrize(
    ("pid", "stock", "lot", "need", "qty", "max_orderable", "orderable", "shortfall", "flags"),
    [
        ("462150", 43, 10, 50, 50, 40, 40, 10, {"LOT_SIZE_CAP", "PARTIAL_STOCK"}),  # X-13: at most 40 kg
        ("462150", 43, 10, 43, 50, 40, 40, 3, {"LOT_SIZE_CAP", "PARTIAL_STOCK"}),
        ("462150", 43, 10, 35, 40, 40, 40, None, set()),
        ("462646", 276, 5, 300, 300, 275, 275, 25, {"LOT_SIZE_CAP", "PARTIAL_STOCK"}),  # X-13: at most 275 kg
        ("462646", 276, 5, 275, 275, 275, 275, None, set()),
    ],
)
def test_lot_size_caps_hold(pid, stock, lot, need, qty, max_orderable, orderable, shortfall, flags):
    meat = CatalogUnits(product_id=pid, sales_unit="KG", base_unit="KG", allowed_lot_size=Decimal(lot))
    plan = plan_quantity(need, "KG", catalog=meat, api_unit="KG", stock_kind="exact", stock_qty=stock)
    assert (plan.qty, plan.max_orderable, plan.orderable_qty, plan.shortfall) == (
        qty,
        max_orderable,
        orderable,
        shortfall,
    )
    assert set(plan.flags) & {"LOT_SIZE_CAP", "PARTIAL_STOCK"} == flags
    assert plan.content.source == "unit_is_kg"


def test_kg_steps_round_up_to_the_lot():
    """F-02: 20 kg of 475594 kirnuvoi in 0.7 kg pieces is 29 x 0.7 = 20.3 kg."""
    butter = CatalogUnits(product_id="475594", sales_unit="KG", base_unit="KG", allowed_lot_size=Decimal("0.7"))
    plan = plan_quantity(20, "KG", catalog=butter, api_unit="KG")
    assert plan.qty == Decimal("20.3") and plan.step == Decimal("0.7") and plan.overshoot == Decimal("0.3")


def test_count_units_are_whole_and_follow_a_lot_above_one():
    cups = CatalogUnits(
        product_id="464997", sales_unit="KI", base_unit="KI", allowed_lot_size=Decimal(2),
        static_content=[static(2, "L", "KI")],
    )  # fmt: skip
    plan = plan_quantity(5, "L", catalog=cups, api_unit="KI")
    assert plan.qty == 4 and plan.total_content == 8  # 3 cases, rounded up to the lot of 2
    assert "OVERSHOOT" in plan.flags


def test_pieces_through_units():
    red_bull = CatalogUnits(product_id="461051", sales_unit="KI", base_unit="ST", units={"KI": 24, "ST": 1})
    assert plan_quantity(48, "PCS", catalog=red_bull, api_unit="KI").qty == 2
    fifty = plan_quantity(50, "PCS", catalog=red_bull, api_unit="KI")
    assert fifty.qty == 3 and fifty.overshoot == 22


def test_exact_ratios_are_not_rounded_up_by_float_noise():
    cream = CatalogUnits(product_id="1", sales_unit="ST", base_unit="ST", static_content=[static(0.1, "L", "ST")])
    assert plan_quantity(0.3, "L", catalog=cream, api_unit="ST").qty == 3
    assert plan_quantity(1000, "L", catalog=MILK_464306, api_unit="ST").qty == 1000


def test_out_of_stock_and_partial_exact_stock():
    zero = plan_quantity(10, "L", catalog=MILK_464306, api_unit="ST", stock_kind="zero", stock_qty=0)
    assert zero.orderable_qty == 0 and zero.shortfall == 10 and "PARTIAL_STOCK" in zero.flags
    part = plan_quantity(1000, "L", catalog=MILK_464306, api_unit="ST", stock_kind="exact", stock_qty=384)
    assert part.orderable_qty == 384 and part.shortfall == 616 and "LOT_SIZE_CAP" not in part.flags


def test_warnings_for_dimension_unit_and_catch_weight():
    flank = CatalogUnits(
        product_id="460675", sales_unit="KG", base_unit="KG", allowed_lot_size=Decimal(10), variable_unit=True
    )
    litres = plan_quantity(5, "L", catalog=flank, api_unit="KG")
    assert litres.qty is None and "DIMENSION_MISMATCH" in litres.flags and "CATCH_WEIGHT" in litres.flags
    guessed = plan_quantity(10, "L", catalog=MILK_464306)
    assert guessed.api_unit == "ST" and "UNIT_NOT_CONFIRMED" in guessed.flags
    unknown = plan_quantity(10, "L", catalog=BUTTER_463233, api_unit="KI")
    assert unknown.qty is None and {"CONTENT_UNKNOWN", "CANNOT_PLAN"} <= set(unknown.flags)
    with pytest.raises(ValueError):
        plan_quantity(10, "gallons", catalog=MILK_464306, api_unit="ST")
    with pytest.raises(ValueError):
        plan_quantity(0, "L", catalog=MILK_464306, api_unit="ST")


def test_api_content_needs_a_comparison_price():
    assert api_content(price(23.42, 11.15, "KG")).value == Decimal("2.100")
    assert api_content(price(6.20)) is None
    assert api_content({"error": True}) is None


def test_catalog_units_from_a_products_json_record():
    record = {
        "id": "461051", "salesUnit": "KI", "baseUnit": "ST", "allowedLotSize": 0.01,
        "units": [{"unitId": "KI", "sizeInBaseUnits": 24.0}, {"unitId": "ST", "sizeInBaseUnits": 1.0}],
        "deposits": [{"material": "4", "unit": "ST", "quantity": 24.0}],
        "synkkaData": {"variableUnit": False},
    }  # fmt: skip
    units = CatalogUnits.from_product(record)
    assert units.size("KI") == 24 and units.size("ST") == 1 and units.size("PAL") is None
    assert units.allowed_lot_size == Decimal("0.01") and units.deposits
