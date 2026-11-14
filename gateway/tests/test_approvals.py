"""The approval API (PLAN M9.1, M9.3, M9.5): the approver's list, the decision and who may make it."""

from decimal import Decimal

import pytest
from app import orders
from app.identity import Buyer
from conftest import voice_headers
from fastapi.testclient import TestClient
from test_orders import order, quote_for, set_product


@pytest.fixture
def head(client) -> TestClient:
    """The head chef (role approver, org kitchen-42) on their own console, with a cookie jar of their own."""
    c = TestClient(client.app)
    assert c.post("/api/login", json={"buyer_id": "head_chef"}).json()["role"] == "approver"
    return c


@pytest.fixture
def pending(chef) -> dict:
    """Chef's W-03 order: EUR 1,010.00 over the EUR 500 cap, waiting for approval."""
    o = order(chef, quote_for(chef, 1000)["quote_id"])
    assert (o["status"], o["reason_code"]) == ("requires_escalation", "limit_exceeded")
    return o


def decide(c: TestClient, approval_id: str, decision: str = "approve", comment: str = "", **headers):
    return c.post(
        f"/v1/approvals/{approval_id}/decision", json={"decision": decision, "comment": comment}, headers=headers
    )


def test_the_approver_lists_the_orgs_pending_approvals(head, pending):
    r = head.get("/v1/approvals").json()
    assert (r["status"], r["reason_code"]) == ("ok", None) and r["message_for_user"]["en"] == "1 approval waiting."
    [a] = r["approvals"]
    assert a == {
        "approval_id": pending["approval_id"],
        "status": "requires_escalation",
        "order_id": pending["order_id"],
        "quote_id": pending["order"]["quote_id"],
        "buyer_name": "Chef Aada (demo)",
        "total_net": "1010.00",
        "total_gross": "1146.35",
        "delivery_date": "2026-11-16",
        "decide_by": "2026-11-15T16:00:00+02:00",  # Sun 17:00 order-by minus 1 hour
        "reasons": ["OVER_ORDER_CAP: EUR 1010.00 is above the EUR 500.00 order cap"],
        "lines": [{"name_fi": a["lines"][0]["name_fi"], "qty": 1000, "api_unit": "ST", "line_net": "1010.00"}],
    }


def test_pending_first_then_newest_first(head, chef):
    first = order(chef, quote_for(chef, 1000)["quote_id"])
    second = order(chef, quote_for(chef, 900, need_date="2026-11-17")["quote_id"])
    third = order(chef, quote_for(chef, 800, need_date="2026-11-18")["quote_id"])
    decide(head, second["approval_id"], "reject")
    ids = [a["approval_id"] for a in head.get("/v1/approvals").json()["approvals"]]
    assert ids == [third["approval_id"], first["approval_id"], second["approval_id"]]


def test_only_the_approvers_own_org(client, pending):
    state = client.app.state.stubs
    stranger = Buyer("x", "Approver elsewhere", "p-x", "kitchen-7", "mandate-x", "approver", "0.00")
    assert orders.list_approvals(state, stranger, "2026-11-14T10:00:00+02:00").approvals == []
    assert orders.decide(state, stranger, pending["approval_id"], "approve", "", "2026-11-14T10:00:00+02:00") is None
    assert orders.get_approval(state, stranger, pending["approval_id"]) is None


def test_a_buyer_session_cannot_list_or_decide(chef, pending):
    assert chef.get("/v1/approvals").status_code == 403
    assert decide(chef, pending["approval_id"]).status_code == 403
    assert chef.get(f"/v1/approvals/{pending['approval_id']}").json()["status"] == "requires_escalation"


def test_voice_headers_and_bearer_keys_cannot_decide(head, chef, pending):
    """M9.5: neither the voice agent nor an external agent approves, even with an approver's cookie alongside."""
    s = head.post("/api/agent-session", json={"mode": "webrtc"}).json()  # the head chef's own voice session
    assert decide(head, pending["approval_id"], **voice_headers(s)).status_code == 403
    assert decide(head, pending["approval_id"], Authorization="Bearer some-agent-key").status_code == 403
    chef.cookies.clear()
    assert decide(chef, pending["approval_id"], **voice_headers(s)).status_code == 403  # no cookie at all
    assert head.get("/v1/approvals", headers=voice_headers(s)).status_code == 403
    assert head.get(f"/v1/approvals/{pending['approval_id']}").json()["status"] == "requires_escalation"


def test_approving_completes_the_order(head, chef, pending):
    r = decide(head, pending["approval_id"], comment="OK for the weekend")
    assert r.status_code == 200
    a = r.json()
    assert (a["status"], a["reason_code"], a["order"]["status"]) == ("completed", None, "completed")
    assert (a["approval"]["outcome"], a["approval"]["decided_by"], a["approval"]["comment"]) == (
        "approved",
        "Head chef Mikko (demo)",
        "OK for the weekend",
    )
    o = chef.get(f"/v1/orders/{pending['order_id']}").json()
    assert (o["status"], o["reason_code"]) == ("completed", None)
    assert head.get(f"/v1/orders/{pending['order_id']}").json()["status"] == "completed"  # same-org approver reads


def test_rejecting_cancels_the_order(head, chef, pending):
    a = decide(head, pending["approval_id"], "reject", "Too much milk").json()
    assert (a["status"], a["reason_code"], a["order"]["status"]) == ("canceled", "approval_rejected", "canceled")
    o = chef.get(f"/v1/orders/{pending['order_id']}").json()
    assert (o["status"], o["reason_code"]) == ("canceled", "approval_rejected")
    assert "rejected" in o["message_for_user"]["en"]
    assert '"Too much milk"' in o["message_for_user"]["en"]


def test_an_expired_approval_cannot_be_approved(head, chef, pending, settings):
    settings.as_of = "2026-11-15T16:00:00+02:00"  # decide_by
    a = decide(head, pending["approval_id"]).json()
    assert (a["status"], a["reason_code"], a["approval"]["outcome"]) == ("canceled", "quote_expired", "expired")
    o = chef.get(f"/v1/orders/{pending['order_id']}").json()
    assert (o["status"], o["reason_code"]) == ("canceled", "quote_expired")


def test_an_unanswered_approval_expires_on_its_own(head, chef, pending, settings):
    settings.as_of = "2026-11-15T16:30:00+02:00"
    assert chef.get(f"/v1/orders/{pending['order_id']}").json()["status"] == "canceled"
    assert head.get("/v1/approvals").json()["approvals"][0]["status"] == "canceled"


def test_deciding_twice_answers_the_first_decision(head, pending):
    first = decide(head, pending["approval_id"]).json()
    again = decide(head, pending["approval_id"], "reject", "changed my mind").json()
    assert again == first


def test_a_price_change_voids_the_approval(head, chef, pending, monkeypatch):
    set_product(monkeypatch, "464306", price=Decimal("1.05"))
    a = decide(head, pending["approval_id"]).json()
    assert (a["status"], a["reason_code"], a["approval"]["outcome"]) == ("canceled", "price_changed", "voided")
    o = chef.get(f"/v1/orders/{pending['order_id']}").json()
    assert (o["status"], o["reason_code"]) == ("requires_escalation", "price_changed")
    assert o["order"]["reasons"] == ["PRICE_CHANGED: line 1 (464306) EUR 1.01 is now EUR 1.05"]


def test_any_change_to_the_quote_voids_the_approval(client, head, pending):
    state = client.app.state.stubs
    qid = pending["order"]["quote_id"]
    state.quotes[qid] = state.quotes[qid].model_copy(update={"total_net": "1.00"})
    a = decide(head, pending["approval_id"]).json()
    assert (a["approval"]["outcome"], a["reason_code"]) == ("voided", "price_changed")
    assert a["order"]["reasons"][0].startswith("QUOTE_CHANGED:")


def test_an_approver_cannot_decide_their_own_order(head):
    o = order(head, quote_for(head, 5000)["quote_id"])  # EUR 5,050 over the head chef's EUR 5,000 cap
    assert o["status"] == "requires_escalation"
    assert decide(head, o["approval_id"]).status_code == 403
