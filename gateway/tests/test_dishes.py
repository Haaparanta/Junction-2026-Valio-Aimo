"""Dish to basket (docs/basket-plan.md M27.1, M27.4): the screen's synchronous route and the plan_dish job path."""

import sqlite3
import threading
import time

import pytest
from app.basket import service
from app.contract import DishBreakdown, DishInput
from app.identity import BUYERS
from app.llm import LLMRefused, LLMUnavailable
from conftest import FakeLLM, voice_headers
from fastapi.testclient import TestClient

CHEF = BUYERS["chef"]
CAKE = {
    "dish": "mansikkakakku",
    "servings": 40,
    "need_date": "2026-11-16",
    "must_claims": ["FREE_FROM_LACTOSE"],
    "must_not_allergens": [],
    "language": "fi",
    "basket_id": "new",
}


def ingredient(iid, fi, en, amount, unit, query, heads, *, claims=(), temp="any", exclude=(), notes=()):
    return {
        "ingredient_id": iid,
        "name": {"fi": fi, "en": en},
        "role": "main",
        "amount": amount,
        "unit": unit,
        "per_serving": 0,
        "search": {
            "query": query,
            "heads": list(heads),
            "exclude": list(exclude),
            "must_claims": list(claims),
            "must_not_allergens": [],
            "temperature": temp,
            "limit": 10,
        },
        "need_date": "2000-01-01",  # the gateway overwrites it
        "notes": list(notes),
    }


LF = ["FREE_FROM_LACTOSE"]
NOTE = {"fi": "Vatkaa kylmänä.", "en": "Whip it cold."}


def cake(inp: DishInput) -> DishBreakdown:
    """A lactose-free mansikkakakku, as Claude might plan it: lactose-free on the dairy only."""
    return DishBreakdown.model_validate(
        {
            "dish": inp.dish,
            "dish_name": {"fi": "Mansikkakakku", "en": "Strawberry cake"},
            "servings": inp.servings,
            "batch_note": {"fi": "Kolme 14 annoksen pellillistä.", "en": "Three trays of 14 portions."},
            "ingredients": [
                ingredient("kerma", "kuohukerma", "whipping cream", 4, "L", "kuohukerma", ["kuohukerma"],
                           claims=LF, temp="chilled", notes=[NOTE]),
                ingredient("munat", "kananmuna", "eggs", 24, "PCS", "kananmuna", ["kananmuna"]),
                ingredient("sokeri", "sokeri", "sugar", 2, "KG", "sokeri", ["sokeri"], exclude=["tomusokeri"],
                           temp="ambient"),
                ingredient("jauho", "vehnäjauho", "wheat flour", 1.5, "KG", "vehnäjauho", ["vehnäjauho"],
                           temp="ambient"),
                ingredient("mansikat", "pakastemansikka", "frozen strawberries", 3, "KG", "mansikka", ["mansikka"],
                           temp="frozen"),
                ingredient("rahka", "laktoositon rahka", "lactose-free quark", 2, "KG", "rahka", ["rahka"],
                           claims=LF, temp="chilled"),
            ],
            "assumptions": [{"fi": "Kakkupohja leivotaan itse.", "en": "The sponge is baked in-house."}],
            "warnings": [],
        }
    )  # fmt: skip


class CakeLLM(FakeLLM):
    def breakdown(self, inp: DishInput) -> DishBreakdown:
        super().breakdown(inp)
        return cake(inp)


@pytest.fixture
def llm(client) -> CakeLLM:
    fake = CakeLLM()
    client.app.state.llm = fake
    return fake


@pytest.fixture
def svc(client, settings):
    return service(client.app, settings)


def plan(c: TestClient, **over) -> dict:
    r = c.post("/v1/baskets/dish", json={**CAKE, **over})
    assert r.status_code == 200, r.text
    return r.json()


def voice(c: TestClient) -> dict:
    r = c.post("/api/agent-session", json={"mode": "webrtc"})
    assert r.status_code == 200
    return voice_headers(r.json())


def plan_job(c: TestClient, headers: dict, **over) -> dict:
    r = c.post("/v1/baskets/dish-jobs", json={**CAKE, **over}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def run(c: TestClient, job_id: str) -> dict:
    r = c.post(f"/v1/baskets/dish-jobs/{job_id}/run")
    assert r.status_code == 200, r.text
    return r.json()


def breakdowns(llm: FakeLLM) -> int:
    return sum(1 for name, _ in llm.calls if name == "breakdown")


# ---- the screen's route ----------------------------------------------------------------------------------------------


def test_a_dish_becomes_priced_basket_lines(chef, llm):
    res = plan(chef)
    dish = res["dish"]
    assert res["reason_code"] is None and dish["dish_name"]["en"] == "Strawberry cake"
    assert (dish["dish"], dish["servings"], dish["need_date"]) == ("mansikkakakku", 40, "2026-11-16")
    assert dish["line_ids"] == [1, 2, 3, 4, 5, 6] and dish["assumptions"][0]["en"] == "The sponge is baked in-house."
    lines = {x["line_id"]: x for x in res["basket"]["lines"]}
    assert all(x["status"] == "priced" and x["source"] == "dish" for x in lines.values())
    assert {x["product_id"] for x in lines.values()} == {"469346", "472535", "468904", "470212", "466932", "465731"}
    cream = lines[1]
    assert cream["need_text"] == "kuohukerma" and cream["notes"] == [NOTE] and cream["need_date"] == "2026-11-16"
    assert (cream["amount"], cream["unit"]) == (4, "L")
    assert res["basket"]["counts"]["priced"] == 6 and res["basket"]["total_net"] != "0.00"
    assert "6 lines, lines 1, 2, 3, 4, 5 and 6" in res["message_for_user"]["en"]
    assert "Check the assumptions" in res["message_for_user"]["en"]
    inp = llm.calls[0][1]
    assert isinstance(inp, DishInput) and inp.must_claims == ["FREE_FROM_LACTOSE"]


def test_dishes_are_persisted_on_the_basket(chef, llm):
    first = plan(chef)
    basket_id = first["basket_id"]
    again = plan(chef, basket_id=basket_id, dish="mustikkapiirakka", servings=20)
    assert again["dish"]["line_ids"] == [7, 8, 9, 10, 11, 12]
    stored = chef.get(f"/v1/baskets/{basket_id}").json()["basket"]
    assert [d["dish"] for d in stored["dishes"]] == ["mansikkakakku", "mustikkapiirakka"]
    assert stored["dishes"][0] == first["dish"] and stored["dish_jobs"] == []
    assert chef.get("/v1/baskets/current").json()["basket"]["dishes"] == stored["dishes"]


def test_a_refusal_is_200_without_a_dish(chef, llm):
    llm.error = LLMRefused("declined")
    res = plan(chef)
    assert res["dish"] is None and res["reason_code"] == "not_found"
    assert res["basket"]["lines"] == [] and "could not plan this dish" in res["message_for_user"]["en"]


def test_no_ingredients_is_200_without_a_dish(chef, client):
    empty = DishBreakdown.model_validate(
        {
            "dish": "x",
            "dish_name": {"fi": "x", "en": "x"},
            "servings": 40,
            "batch_note": {"fi": "", "en": ""},
            "ingredients": [],
            "assumptions": [],
            "warnings": [{"fi": "Ei ruokalaji.", "en": "Not a dish."}],
        }
    )
    client.app.state.llm = FakeLLM(dish=empty)
    res = plan(chef, dish="asdfgh")
    assert res["dish"] is None and res["reason_code"] == "not_found" and "Not a dish." in res["warnings"]
    assert "Not a dish." in res["message_for_user"]["en"]


def test_the_ai_service_unavailable_is_503(chef, llm):
    llm.error = LLMUnavailable("no credentials")
    r = chef.post("/v1/baskets/dish", json=CAKE)
    assert r.status_code == 503
    assert r.json()["detail"] == "The AI service is unavailable right now. Try again in a moment."


def test_an_ordered_basket_is_locked_before_claude(chef, llm, svc):
    basket_id = plan(chef)["basket_id"]
    svc.mark_ordered(CHEF, basket_id)
    llm.calls.clear()
    res = plan(chef, basket_id=basket_id)
    assert res["reason_code"] == "basket_locked" and res["dish"] is None and llm.calls == []
    assert len(res["basket"]["lines"]) == 6


def test_an_identity_argument_is_ignored(chef, llm):
    res = plan(chef, buyer_id="head_chef", buyer="head_chef")
    assert res["basket"]["buyer_id"] == "chef"


def test_a_date_that_does_not_exist_is_422(chef, llm):
    assert chef.post("/v1/baskets/dish", json={**CAKE, "need_date": "2026-02-30"}).status_code == 422
    assert llm.calls == []


def test_the_dish_route_needs_the_buyer_cookie(client, chef, llm):
    assert TestClient(client.app).post("/v1/baskets/dish", json=CAKE).status_code == 401
    headers = voice(chef)
    assert TestClient(client.app).post("/v1/baskets/dish", json=CAKE, headers=headers).status_code == 401
    assert llm.calls == []


def test_another_buyers_basket_is_not_found(client, chef, llm):
    basket_id = plan(chef)["basket_id"]
    other = TestClient(client.app)
    assert other.post("/api/login", json={"buyer_id": "head_chef"}).status_code == 200
    assert other.post("/v1/baskets/dish", json={**CAKE, "basket_id": basket_id}).status_code == 404


# ---- plan_dish: the voice path ---------------------------------------------------------------------------------------


def test_plan_dish_answers_at_once_and_the_page_runs_the_job(chef, llm):
    job = plan_job(chef, voice(chef))
    assert job["state"] == "pending" and job["status"] == "incomplete" and job["result"] is None
    assert job["job_id"].startswith("J-") and len(job["job_id"]) == 12 and job["basket_id"].startswith("B-")
    assert "about half a minute" in job["message_for_user"]["en"] and llm.calls == []
    basket = chef.get(f"/v1/baskets/{job['basket_id']}").json()["basket"]
    assert basket["dish_jobs"] == [job["job_id"]] and basket["lines"] == []
    done = run(chef, job["job_id"])
    assert done["state"] == "done" and done["status"] == "ok" and breakdowns(llm) == 1
    assert done["result"]["dish"]["line_ids"] == [1, 2, 3, 4, 5, 6]
    assert done["message_for_user"] == done["result"]["message_for_user"]
    basket = chef.get(f"/v1/baskets/{job['basket_id']}").json()["basket"]
    assert basket["dish_jobs"] == [] and len(basket["dishes"]) == 1 and len(basket["lines"]) == 6
    assert run(chef, job["job_id"]) == done and breakdowns(llm) == 1  # a finished job is not run again
    assert chef.get(f"/v1/baskets/dish-jobs/{job['job_id']}").json() == done


def test_plan_dish_is_an_agent_tool(settings):
    from app.main import create_app

    paths = create_app(settings).openapi()["paths"]
    op = paths["/v1/baskets/dish-jobs"]["post"]
    assert op["operationId"] == "plan_dish" and op["tags"] == ["agent-tools"]
    x = op["x-agent-tool"]
    assert x["pre_tool_speech"] == "force" and x["response_timeout_secs"] == 15
    assert {"job_id", "basket_id", "state"} <= set(x["response_filter"]) and "show_basket" in x["description"]
    assert paths["/v1/baskets/dish-jobs/{job_id}/run"]["post"]["tags"] == ["ui"]
    assert paths["/v1/baskets/dish-jobs/{job_id}"]["get"]["tags"] == ["ui"]
    assert paths["/v1/baskets/dish"]["post"]["tags"] == ["ui"]


def test_the_same_request_in_the_same_conversation_reuses_the_job(chef, llm):
    headers = voice(chef)
    job = plan_job(chef, headers)
    assert plan_job(chef, headers, dish="  Mansikkakakku ")["job_id"] == job["job_id"]
    assert plan_job(chef, headers, basket_id=job["basket_id"])["job_id"] == job["job_id"]
    run(chef, job["job_id"])
    again = plan_job(chef, headers)  # done: the result again, not a second dish
    assert again["job_id"] == job["job_id"] and again["state"] == "done"
    other = plan_job(chef, headers, servings=80)
    assert other["job_id"] != job["job_id"] and other["basket_id"] == job["basket_id"]  # the call's basket
    elsewhere = plan_job(chef, voice(chef))
    assert elsewhere["job_id"] != job["job_id"] and elsewhere["basket_id"] != job["basket_id"]


def test_two_runs_at_once_plan_the_dish_once(client, chef, settings):
    entered, release = threading.Event(), threading.Event()

    class SlowLLM(CakeLLM):
        def breakdown(self, inp: DishInput) -> DishBreakdown:
            entered.set()
            assert release.wait(10)
            return super().breakdown(inp)

    slow = SlowLLM()
    client.app.state.llm = slow
    job = plan_job(chef, voice(chef))
    tabs = [TestClient(client.app), TestClient(client.app)]
    for tab in tabs:  # two tabs of the same buyer
        assert tab.post("/api/login", json={"buyer_id": "chef"}).status_code == 200
    first: dict = {}
    t = threading.Thread(target=lambda: first.update(run(tabs[0], job["job_id"])))
    t.start()
    assert entered.wait(10)
    second = run(tabs[1], job["job_id"])
    assert second["state"] == "running" and second["result"] is None
    release.set()
    t.join(10)
    assert first["state"] == "done" and breakdowns(slow) == 1
    assert len(chef.get(f"/v1/baskets/{job['basket_id']}").json()["basket"]["lines"]) == 6


def test_a_stale_running_job_is_claimed_again(chef, llm, settings):
    job = plan_job(chef, voice(chef))
    with sqlite3.connect(settings.db_path) as db:
        db.execute(
            "UPDATE dish_job SET state = 'running', updated_at = ? WHERE job_id = ?", (time.time(), job["job_id"])
        )
    assert run(chef, job["job_id"])["state"] == "running" and llm.calls == []  # another run holds it
    with sqlite3.connect(settings.db_path) as db:
        db.execute("UPDATE dish_job SET updated_at = ? WHERE job_id = ?", (time.time() - 181, job["job_id"]))
    assert run(chef, job["job_id"])["state"] == "done" and breakdowns(llm) == 1


def test_another_buyers_job_is_not_found(client, chef, llm):
    job = plan_job(chef, voice(chef))
    other = TestClient(client.app)
    assert other.post("/api/login", json={"buyer_id": "head_chef"}).status_code == 200
    assert other.post(f"/v1/baskets/dish-jobs/{job['job_id']}/run").status_code == 404
    assert other.get(f"/v1/baskets/dish-jobs/{job['job_id']}").status_code == 404
    assert chef.get("/v1/baskets/dish-jobs/J-0000000000").status_code == 404
    assert chef.get("/v1/baskets/dish-jobs/nonsense").status_code == 422
    assert llm.calls == []


def test_running_a_job_needs_the_buyer_cookie(client, chef, llm):
    headers = voice(chef)
    job = plan_job(chef, headers)
    voice_only = TestClient(client.app)
    assert voice_only.post(f"/v1/baskets/dish-jobs/{job['job_id']}/run", headers=headers).status_code == 401
    assert voice_only.get(f"/v1/baskets/dish-jobs/{job['job_id']}", headers=headers).status_code == 401
    assert plan_job(voice_only, headers)["job_id"] == job["job_id"]  # the tool itself takes the voice headers


def test_a_refused_job_is_done_without_a_dish(chef, llm):
    llm.error = LLMRefused("declined")
    job = plan_job(chef, voice(chef))
    done = run(chef, job["job_id"])
    assert done["state"] == "done" and done["reason_code"] == "not_found" and done["result"]["dish"] is None


def test_an_unavailable_ai_fails_the_job_and_a_retry_makes_a_new_one(chef, llm):
    headers = voice(chef)
    llm.error = LLMUnavailable("no credentials")
    job = plan_job(chef, headers)
    failed = run(chef, job["job_id"])
    assert failed["state"] == "failed" and failed["result"] is None
    assert "AI service is unavailable" in failed["message_for_user"]["en"]
    basket = chef.get(f"/v1/baskets/{job['basket_id']}").json()["basket"]
    assert basket["dish_jobs"] == [] and basket["lines"] == []
    llm.error = None
    retry = plan_job(chef, headers)
    assert retry["job_id"] != job["job_id"] and retry["basket_id"] == job["basket_id"]
    assert run(chef, retry["job_id"])["state"] == "done"


def test_plan_dish_on_an_ordered_basket_is_locked(chef, llm, svc):
    basket_id = plan(chef)["basket_id"]
    svc.mark_ordered(CHEF, basket_id)
    res = plan_job(chef, voice(chef), basket_id=basket_id)
    assert res["reason_code"] == "basket_locked" and res["state"] == "failed" and res["job_id"] == ""


def test_plan_dish_ignores_an_identity_argument(client, chef, llm):
    job = plan_job(chef, voice(chef), buyer_id="head_chef")
    other = TestClient(client.app)
    assert other.post("/api/login", json={"buyer_id": "head_chef"}).status_code == 200
    assert other.get(f"/v1/baskets/{job['basket_id']}").status_code == 404
    assert run(chef, job["job_id"])["result"]["basket"]["buyer_id"] == "chef"
