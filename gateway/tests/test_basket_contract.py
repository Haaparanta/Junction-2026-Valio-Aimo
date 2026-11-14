"""Contract for the basket, the imports and plan_dish (docs/basket-plan.md M21.3), before the routes exist."""

import pytest
from app.contract import (
    AddToBasketRequest,
    BasketLinePatch,
    BasketLineRequest,
    BasketRequest,
    DishBreakdown,
    ListExtraction,
    PlanDishRequest,
    UpdateBasketLineRequest,
)
from conftest import voice_headers
from pydantic import ValidationError

AGENT_REQUESTS = [
    AddToBasketRequest,
    UpdateBasketLineRequest,
    BasketLineRequest,
    BasketRequest,
    PlanDishRequest,
    BasketLinePatch,  # the UI PATCH body; same rules, so a later agent tool can reuse it
]


@pytest.mark.parametrize("model", AGENT_REQUESTS, ids=lambda m: m.__name__)
def test_new_request_schemas_are_flat_and_described(model):
    """Same rule as the §5 tools: ElevenLabs reads these as webhook tool schemas."""
    for prop, s in model.model_json_schema()["properties"].items():
        assert "anyOf" not in s and "$ref" not in s, (model.__name__, prop)
        assert s.get("description"), (model.__name__, prop)


def test_patch_sentinels_mean_unchanged():
    p = BasketLinePatch()
    assert (p.amount, p.unit, p.need_date, p.offer_id) == (0, "", "", "")
    u = UpdateBasketLineRequest(basket_id="B-TEST", line_id=1)
    assert (u.amount, u.unit, u.need_date, u.offer_id) == (0, "", "", "")
    with pytest.raises(ValidationError):
        BasketLinePatch(need_date="16.11.2026")  # only ISO dates, or empty


def test_identity_is_not_a_request_field():
    """A buyer argument is ignored, never stored (PLAN M7.4)."""
    r = AddToBasketRequest(
        basket_id="new", query="voi", amount=20, unit="KG", need_date="2026-11-16", buyer_id="head_chef"
    )
    assert "buyer_id" not in r.model_dump()


DISH = {
    "dish": "mansikkakakku",
    "dish_name": {"fi": "Mansikkakakku", "en": "Strawberry cake"},
    "servings": 40,
    "batch_note": {"fi": "Noin 5 kakkua.", "en": "About 5 cakes."},
    "ingredients": [
        {
            "ingredient_id": "kerma",
            "name": {"fi": "kuohukerma", "en": "whipping cream"},
            "role": "main",
            "amount": 4.0,
            "unit": "L",
            "per_serving": 0.1,
            "search": {
                "query": "laktoositon kuohukerma",
                "heads": ["kerma", "kuohukerma"],
                "exclude": ["kasvirasva"],
                "must_claims": ["FREE_FROM_LACTOSE"],
                "must_not_allergens": [],
                "temperature": "chilled",
                "limit": 10,
            },
            "need_date": "2026-11-16",
            "notes": [],
        }
    ],
    "assumptions": [],
    "warnings": [],
}


def test_dish_breakdown_accepts_the_prompt_example():
    d = DishBreakdown.model_validate(DISH)
    assert d.ingredients[0].search.must_claims == ["FREE_FROM_LACTOSE"]


@pytest.mark.parametrize(
    "where",
    [
        lambda d: d,
        lambda d: d["ingredients"][0],
        lambda d: d["ingredients"][0]["search"],
    ],
    ids=["dish", "ingredient", "search"],
)
def test_dish_breakdown_rejects_prices_and_ids(where):
    """B-12: prices and product ids come only from the gateway, so the model may not add them anywhere."""
    import copy

    bad = copy.deepcopy(DISH)
    where(bad)["unit_price_net"] = "1.01"
    with pytest.raises(ValidationError):
        DishBreakdown.model_validate(bad)


def test_dish_breakdown_rejects_other_units_and_codes():
    import copy

    bad = copy.deepcopy(DISH)
    bad["ingredients"][0]["unit"] = "ST"
    with pytest.raises(ValidationError):
        DishBreakdown.model_validate(bad)
    with pytest.raises(ValidationError):
        PlanDishRequest(dish="kakku", servings=8, need_date="2026-11-16", must_not_allergens=["MILK"], basket_id="new")


def test_list_extraction_allows_unread_amounts_but_no_extra_fields():
    item = {"raw_text": "voi", "name": "voi", "quantity": None, "unit": None, "note": "", "confidence": "low"}
    x = ListExtraction.model_validate({"items": [item], "handwritten": True, "unreadable": [], "need_date": None})
    assert x.items[0].quantity is None
    extra = {"items": [{**item, "product_id": "464076"}], "handwritten": True, "unreadable": [], "need_date": None}
    with pytest.raises(ValidationError):
        ListExtraction.model_validate(extra)


def test_quote_lines_carry_their_delivery_date(chef):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    h = voice_headers(s)
    need = {"query": "laktoositon maito", "heads": ["maito"], "amount": 1000, "unit": "L", "need_date": "2026-11-16"}
    best = chef.post("/v1/offers", json=need, headers=h).json()["options"][0]
    q = chef.post("/v1/quotes", json={"offer_id": best["offer_id"]}, headers=h).json()["quote"]
    assert [line["delivery_date"] for line in q["lines"]] == [q["delivery_date"]] == [best["delivery_date"]]
    assert q["basket_id"] is None  # a single-offer quote has no basket and is never stale
