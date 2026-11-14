"""The headline example W-03 through the stubs: offers, quote, confirm, order -> requires_escalation."""

from conftest import voice_headers

NEED = {
    "query": "laktoositon maito",
    "heads": ["maito", "maitojuoma"],
    "must_claims": ["FREE_FROM_LACTOSE"],
    "amount": 1000,
    "unit": "L",
    "need_date": "2026-11-16",
}


def start_voice(client) -> dict:
    r = client.post("/api/agent-session", json={"mode": "webrtc"})
    assert r.status_code == 200
    return r.json()


def test_headline_flow_over_voice_tools(chef):
    s = start_voice(chef)
    h = voice_headers(s)

    offers = chef.post("/v1/offers", json=NEED, headers=h).json()
    assert offers["status"] == "ok"
    best = offers["options"][0]
    assert chef.get(f"/v1/offers/{offers['offer_set_id']}").json()["options"][0]["offer_id"] == best["offer_id"]
    assert (best["product_id"], best["qty"], best["total_net"], best["tier"]) == ("464306", 1000, "1010.00", "best")
    assert "VARIANT" not in {f for o in offers["options"] for f in o["flags"]}  # coffee milk only with consent
    assert {n["product_id"] for n in offers["not_offered"] if "CUTOFF_PASSED" in n["flags"]} >= {"463038"}

    q = chef.post("/v1/quotes", json={"offer_id": best["offer_id"]}, headers=h).json()
    assert (q["status"], q["total_net"], q["total_gross"]) == ("ready_for_complete", "1010.00", "1146.35")
    again = chef.post("/v1/quotes", json={"offer_id": best["offer_id"]}, headers=h).json()
    assert again["quote_id"] == q["quote_id"]  # idempotent

    # Not confirmed on screen yet: the gateway refuses.
    o = chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers=h).json()
    assert (o["status"], o["reason_code"]) == ("incomplete", "confirmation_required")

    # Only the buyer's web session can confirm, never the voice headers.
    chef.cookies.clear()
    assert chef.post(f"/v1/quotes/{q['quote_id']}/confirm", headers=h).status_code == 401
    chef.post("/api/login", json={"buyer_id": "chef"})
    assert chef.post(f"/v1/quotes/{q['quote_id']}/confirm").json()["confirmed"] is True

    o1 = chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers=h).json()
    o2 = chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers=h).json()
    assert (o1["status"], o1["reason_code"]) == ("requires_escalation", "limit_exceeded")
    assert o1["order_id"] == o2["order_id"]  # saying "tilaa" twice places one order
    assert o1["message_for_user"]["fi"] and o1["message_for_user"]["en"]

    assert chef.get(f"/v1/orders/{o1['order_id']}", headers=h).json()["status"] == "requires_escalation"
    a = chef.get(f"/v1/approvals/{o1['approval_id']}", headers=h).json()
    assert any("OVER_ORDER_CAP" in r for r in a["approval"]["reasons"])

    # The UI reads the quote by id with the buyer cookie.
    assert chef.get(f"/v1/quotes/{q['quote_id']}").json()["total_net"] == "1010.00"


def test_buyer_argument_cannot_change_identity(chef):
    s = start_voice(chef)
    body = {**NEED, "buyer": "head_chef", "buyer_id": "head_chef"}
    r = chef.post("/v1/offers", json=body, headers=voice_headers(s))
    assert r.status_code == 200
    q = chef.post(
        "/v1/quotes",
        json={"offer_id": r.json()["options"][0]["offer_id"], "buyer_id": "head_chef"},
        headers=voice_headers(s),
    ).json()
    assert q["quote"]["buyer_id"] == "chef"


def test_unknown_offer_is_404(chef):
    s = start_voice(chef)
    assert chef.post("/v1/quotes", json={"offer_id": "OS-NOPE:464306"}, headers=voice_headers(s)).status_code == 404
