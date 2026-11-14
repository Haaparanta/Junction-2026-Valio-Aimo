"""Orders (PLAN M8.1-8.3): the state machine, idempotency, the pre-order re-check and the policy at place_order."""

import dataclasses
from decimal import Decimal

import pytest
from app import orders, stubs
from app.contract import OffersRequest, Order
from app.identity import BUYERS
from conftest import voice_headers
from fastapi.testclient import TestClient

MILK = {
    "query": "laktoositon maito",
    "heads": ["maito", "maitojuoma"],
    "must_claims": ["FREE_FROM_LACTOSE"],
    "amount": 1000,
    "unit": "L",
    "need_date": "2026-11-16",
}


def quote_for(c: TestClient, amount: float = 396, option: int = 0, **need) -> dict:
    """A confirmed quote for `amount` L of lactose-free milk (396 L of 464306 is EUR 399.96)."""
    offers = c.post("/v1/offers", json={**MILK, "amount": amount, **need}).json()
    q = c.post("/v1/quotes", json={"offer_id": offers["options"][option]["offer_id"]}).json()
    assert c.post(f"/v1/quotes/{q['quote_id']}/confirm").json()["confirmed"] is True
    return q


def order(c: TestClient, quote_id: str, **headers) -> dict:
    r = c.post("/v1/orders", json={"quote_id": quote_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def set_product(monkeypatch, product_id: str, **change) -> None:
    """Swap a stub row between quote and order, as a changed /price or /availability answer would (M8.3)."""
    monkeypatch.setitem(stubs.PRODUCTS, product_id, dataclasses.replace(stubs.PRODUCTS[product_id], **change))


# ---- M8.1 the state machine ---------------------------------------------------------------------


def test_the_state_machine_allows_only_ucp_moves():
    o = Order(
        order_id="O-1", quote_id="Q-1", status="incomplete", total_net="1.00", total_gross="1.14",
        delivery_date="2026-11-16", created_at="2026-11-14T10:00:00+02:00",
    )  # fmt: skip
    done = orders.transition(orders.transition(o, "ready_for_complete"), "completed")
    assert done.status == "completed"
    for final in (done, orders.transition(o, "canceled")):
        for to in ("incomplete", "ready_for_complete", "requires_escalation", "completed", "canceled"):
            with pytest.raises(orders.IllegalTransition):
                orders.transition(final, to)
    with pytest.raises(orders.IllegalTransition):
        orders.transition(o, "completed")  # never straight to completed


def test_within_the_mandate_the_order_completes(chef):
    o = order(chef, quote_for(chef)["quote_id"])
    assert (o["status"], o["reason_code"], o["approval_id"], o["total_net"]) == ("completed", None, None, "399.96")
    assert o["order"]["completed_at"] and o["message_for_user"]["fi"].startswith(f"Tilaus {o['order_id']}")


def test_an_order_needs_a_confirmed_unexpired_quote(chef, settings):
    offers = chef.post("/v1/offers", json={**MILK, "amount": 396}).json()
    q = chef.post("/v1/quotes", json={"offer_id": offers["options"][0]["offer_id"]}).json()
    assert (order(chef, q["quote_id"])["reason_code"]) == "confirmation_required"
    assert chef.post(f"/v1/quotes/{q['quote_id']}/confirm").json()["confirmed"] is True
    settings.as_of = "2026-11-14T10:20:00+02:00"  # the quote's price was fixed until 10:15
    o = order(chef, q["quote_id"])
    assert (o["status"], o["reason_code"], o["order_id"]) == ("incomplete", "quote_expired", None)
    assert order(chef, "Q-NOPE")["reason_code"] == "not_found"


def test_an_expired_quote_cannot_be_confirmed(chef, settings):
    offers = chef.post("/v1/offers", json={**MILK, "amount": 396}).json()
    q = chef.post("/v1/quotes", json={"offer_id": offers["options"][0]["offer_id"]}).json()
    settings.as_of = "2026-11-14T10:15:00+02:00"
    c = chef.post(f"/v1/quotes/{q['quote_id']}/confirm").json()
    assert (c["status"], c["reason_code"], c["confirmed"]) == ("incomplete", "quote_expired", False)


# ---- M8.2 idempotency ---------------------------------------------------------------------------


def test_the_same_key_and_payload_answer_the_same_order(chef):
    q = quote_for(chef)
    a = order(chef, q["quote_id"], **{"Idempotency-Key": "k-1"})
    b = order(chef, q["quote_id"], **{"Idempotency-Key": "k-1"})
    assert a["order_id"] == b["order_id"] and b["status"] == "completed"
    assert order(chef, q["quote_id"])["order_id"] == a["order_id"]  # one order per quote, whatever the key
    assert len(chef.app.state.stubs.orders) == 1


def test_the_same_key_with_another_payload_is_409(chef):
    first, second = quote_for(chef), quote_for(chef, need_date="2026-11-17")
    order(chef, first["quote_id"], **{"Idempotency-Key": "k-2"})
    r = chef.post("/v1/orders", json={"quote_id": second["quote_id"]}, headers={"Idempotency-Key": "k-2"})
    assert r.status_code == 409
    assert order(chef, second["quote_id"], **{"Idempotency-Key": "k-3"})["status"] == "completed"


def test_saying_tilaa_twice_over_voice_places_one_order(chef):
    q = quote_for(chef)
    h = voice_headers(chef.post("/api/agent-session", json={"mode": "webrtc"}).json())
    assert order(chef, q["quote_id"], **h)["order_id"] == order(chef, q["quote_id"], **h)["order_id"]


# ---- M8.3 the pre-order re-check ----------------------------------------------------------------


def test_a_price_change_after_the_quote_escalates_and_asks_for_a_new_quote(chef, monkeypatch):
    q = quote_for(chef)
    set_product(monkeypatch, "464306", price=Decimal("1.11"))
    o = order(chef, q["quote_id"])
    assert (o["status"], o["reason_code"], o["approval_id"]) == ("requires_escalation", "price_changed", None)
    assert o["order"]["reasons"] == ["PRICE_CHANGED: line 1 (464306) EUR 1.01 is now EUR 1.11"]
    assert "new quote" in o["message_for_user"]["en"]
    assert chef.get(f"/v1/quotes/{q['quote_id']}").status_code == 404  # the old price cannot be ordered again
    assert chef.get(f"/v1/orders/{o['order_id']}").json()["status"] == "requires_escalation"

    offers = chef.post("/v1/offers", json={**MILK, "amount": 396}).json()
    same = next(x for x in offers["options"] if x["product_id"] == "464306")
    new = chef.post("/v1/quotes", json={"offer_id": same["offer_id"]}).json()
    assert new["quote_id"] == q["quote_id"]  # the same offer, priced again
    assert (new["total_net"], new["quote"]["confirmed"]) == ("439.56", False)  # a new price needs a new confirmation
    assert order(chef, new["quote_id"])["reason_code"] == "confirmation_required"
    assert chef.post(f"/v1/quotes/{new['quote_id']}/confirm").json()["confirmed"] is True
    again = order(chef, new["quote_id"])
    assert again["status"] == "completed" and again["order_id"] != o["order_id"]


def test_an_availability_change_after_the_quote_escalates(chef, monkeypatch):
    q = quote_for(chef)
    set_product(monkeypatch, "464306", stock="none")
    o = order(chef, q["quote_id"])
    assert (o["status"], o["reason_code"]) == ("requires_escalation", "price_changed")
    assert o["order"]["reasons"] == ["OUT_OF_STOCK: line 1 (464306) for 2026-11-16"]


# ---- M7 at place_order --------------------------------------------------------------------------


def test_three_400_eur_orders_for_one_delivery_date(chef):
    """R-07: the cap applies per requisition, so a need cannot be split into orders below it."""
    answers = [order(chef, quote_for(chef, amount)["quote_id"]) for amount in (396, 395, 394)]
    assert [a["status"] for a in answers] == ["completed", "requires_escalation", "requires_escalation"]
    assert [a["reason_code"] for a in answers] == [None, "limit_exceeded", "limit_exceeded"]
    second = chef.get(f"/v1/approvals/{answers[1]['approval_id']}").json()["approval"]["reasons"]
    third = chef.get(f"/v1/approvals/{answers[2]['approval_id']}").json()["approval"]["reasons"]
    assert second == [
        "OVER_REQUISITION_CAP: EUR 798.91 for delivery on 2026-11-16, with 1 other open order, "
        "is above the EUR 500.00 order cap"
    ]
    assert "EUR 1196.85" in third[0] and "with 2 other open orders" in third[0]
    # Another delivery date is its own requisition.
    assert order(chef, quote_for(chef, 396, need_date="2026-11-17")["quote_id"])["status"] == "completed"


def test_a_denied_order_is_canceled_with_its_reason(chef, monkeypatch):
    q = quote_for(chef)
    set_product(monkeypatch, "464306", claims=())  # the record no longer says lactose-free
    o = order(chef, q["quote_id"])
    assert (o["status"], o["reason_code"], o["approval_id"]) == ("canceled", "policy_denied", None)
    assert o["order"]["reasons"] == ["ALLERGEN_CONFLICT: line 1 (464306) lacks FREE_FROM_LACTOSE"]
    assert "cannot be placed" in o["message_for_user"]["en"]


def test_a_buyer_argument_changes_nothing(chef):
    q = quote_for(chef, 1000)
    r = chef.post("/v1/orders", json={"quote_id": q["quote_id"], "buyer_id": "head_chef", "mandate_id": "x"}).json()
    assert (r["status"], r["reason_code"]) == ("requires_escalation", "limit_exceeded")


def test_every_external_agent_order_needs_approval(client, settings):
    state, agent = client.app.state.stubs, BUYERS["external_agent"]
    offers = state.get_offers(OffersRequest(**{**MILK, "amount": 10}), settings.as_of)
    q = state.create_quote(agent, offers.options[0].offer_id, settings.as_of)
    state.confirm(agent, q.quote_id, settings.as_of)  # its own place_order call is its confirmation (M8.1)
    o = orders.place_order(state, agent, q.quote_id, None, "mcp:external_agent", "{}", settings.as_of)
    assert (o.status, o.reason_code) == ("requires_escalation", "approval_required")
    assert state.approvals[o.approval_id].reasons == [
        "MANDATE_REQUIRES_APPROVAL: every order under this mandate needs approval"
    ]


def test_cancel_withdraws_a_pending_approval_and_never_undoes_a_completed_order(chef):
    done = order(chef, quote_for(chef)["quote_id"])
    assert chef.post(f"/v1/orders/{done['order_id']}/cancel", json={}).json()["status"] == "completed"
    pending = order(chef, quote_for(chef, 1000)["quote_id"])
    c = chef.post(f"/v1/orders/{pending['order_id']}/cancel", json={}).json()
    assert c["status"] == "canceled"
    a = chef.get(f"/v1/approvals/{pending['approval_id']}").json()
    assert (a["status"], a["approval"]["outcome"]) == ("canceled", "withdrawn")
