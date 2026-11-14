"""The audit trail (PLAN M10.1-10.3): append-only, hash-chained, one event per call, per-order timelines."""

import json
import sqlite3

import pytest
from app import identity, signing
from app.audit import GENESIS, AuditLog
from app.identity import Buyer, key_hash
from app.main import create_app
from conftest import PLATFORM_KEY, FakeLLM, FakeVoice, voice_headers
from fastapi.testclient import TestClient
from test_approvals import decide
from test_imports import CSV, imported
from test_mcp import AGENT_KEY, NEED, call
from test_orders import MILK, order, quote_for
from test_post_call_webhook import PAYLOAD, sign


def trail(c: TestClient) -> AuditLog:
    return c.app.state.stubs.audit


def rows(c: TestClient) -> list[tuple]:
    with sqlite3.connect(c.app.state.store.path) as db:
        return db.execute("SELECT seq, entry, hash FROM audit_event ORDER BY seq").fetchall()


def tamper(c: TestClient, sql: str, *args) -> None:
    """An attacker with write access to the database file: drop the append-only triggers, then edit."""
    with sqlite3.connect(c.app.state.store.path) as db:
        db.execute("DROP TRIGGER IF EXISTS audit_event_no_update")
        db.execute("DROP TRIGGER IF EXISTS audit_event_no_delete")
        db.execute(sql, args)


def timeline(c: TestClient, order_id: str) -> dict:
    r = c.get(f"/v1/orders/{order_id}/audit")
    assert r.status_code == 200, r.text
    return r.json()


def session_for(c: TestClient, buyer_id: str) -> TestClient:
    """A web session of its own for any BUYERS entry (the demo login only offers chef and head_chef)."""
    other = TestClient(c.app)
    other.cookies.set(identity.COOKIE, c.app.state.store.create_web_session(buyer_id, 600))
    return other


@pytest.fixture
def head(client) -> TestClient:
    return session_for(client, "head_chef")


@pytest.fixture
def agent(settings):
    """MCP under the external agent's bearer key (as test_mcp's fixture)."""
    settings.mcp_agent_keys = {"test-agent": key_hash(AGENT_KEY)}
    settings.mcp_allowed_hosts = ["testserver"]
    with TestClient(create_app(settings, voice=FakeVoice(), llm=FakeLLM())) as c:
        yield c


# ---- M10.2 every quote and order has a complete chain -------------------------------------------


def test_a_voice_order_and_its_approval_have_a_complete_chain(chef, head):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    h = voice_headers(s)
    offers = chef.post("/v1/offers", json={**MILK, "amount": 1000}, headers=h).json()
    q = chef.post("/v1/quotes", json={"offer_id": offers["options"][0]["offer_id"]}, headers=h).json()
    assert chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers=h).json()["reason_code"] == (
        "confirmation_required"
    )
    chef.post(f"/v1/quotes/{q['quote_id']}/confirm")
    o = chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers=h).json()
    assert o["status"] == "requires_escalation"
    decide(head, o["approval_id"], "approve", "Ok, tarvitaan.")

    t = timeline(chef, o["order_id"])
    assert t["status"] == "ok" and t["chain_ok"] is True and t["order_id"] == o["order_id"]
    ev = t["events"]
    assert [(e["action"], e["channel"], e["decision"]) for e in ev] == [
        ("quote.create", "voice", "ready_for_complete"),
        ("order.place", "voice", "incomplete/confirmation_required"),
        ("quote.confirm", "web", "confirmed"),
        ("order.place", "voice", "requires_escalation/limit_exceeded"),
        ("approval.decide", "web", "approve -> approved"),
    ]
    assert [e["seq"] for e in ev] == sorted(e["seq"] for e in ev)  # oldest first
    assert all(e["conversation_id"] == s["conversation_id"] for e in ev if e["channel"] == "voice")
    assert ev[0]["actor"] == "Chef Aada (demo)" and ev[-1]["actor"] == "Head chef Mikko (demo)"
    assert ev[3]["reasons"] == ["OVER_ORDER_CAP: EUR 1010.00 is above the EUR 500.00 order cap"]
    assert ev[-1]["inputs"] == {"decision": "approve", "comment": "Ok, tarvitaan."}
    assert ev[0]["at"] == "2026-11-14T10:00:00+02:00"  # the as-of time of the demo clock
    assert ev[0]["detail"]["fi"] and ev[0]["detail"]["en"] and ev[0]["summary"]
    # The response hashes: the answer, plus the signed quote; the approval's event carries the receipt's hash.
    assert signing.sha256_hex(q["quote"]["quote_jws"]) in ev[0]["response_sha256"]
    receipt = chef.get(f"/v1/orders/{o['order_id']}").json()["order"]["receipt_jws"]
    assert signing.sha256_hex(receipt) in ev[-1]["response_sha256"]

    # Every event links to the entry before it in the whole trail, and every hash recomputes.
    chain = {seq: (json.loads(entry), h) for seq, entry, h in rows(chef)}
    for e in ev:
        body, h = chain[e["seq"]]
        assert e["hash"] == h == signing.sha256_hex(signing.canonical(body))
        assert e["prev_hash"] == (chain[e["seq"] - 1][1] if e["seq"] > 1 else GENESIS)


def test_a_web_order_within_the_mandate_has_quote_confirm_and_order(chef):
    q = quote_for(chef)
    o = order(chef, q["quote_id"])
    ev = timeline(chef, o["order_id"])["events"]
    assert [e["action"] for e in ev] == ["quote.create", "quote.confirm", "order.place"]
    assert ev[-1]["decision"] == "completed" and ev[-1]["order_id"] == o["order_id"]
    assert signing.sha256_hex(o["order"]["receipt_jws"]) in ev[-1]["response_sha256"]
    assert ev[-1]["inputs"]["confirmation"] == "on-screen Confirm"


def test_a_basket_order_shows_the_import_and_the_basket_quote(chef):
    res = imported(chef, "tuotenumero;määrä;yksikkö;toimituspäivä\n464306;100;l;16.11.2026\n")
    b = res["basket_id"]
    bq = chef.post("/v1/baskets/quote", json={"basket_id": b}).json()
    chef.post(f"/v1/quotes/{bq['quote_id']}/confirm")
    o = order(chef, bq["quote_id"])
    ev = timeline(chef, o["order_id"])["events"]
    assert [e["action"] for e in ev] == ["basket.import", "basket.quote", "quote.confirm", "order.place"]
    imp = ev[0]["inputs"]
    assert imp["kind"] == "sheet" and imp["rows"] == 1 and len(imp["file_sha256"]) == 64
    assert "464306;100" not in json.dumps(ev)  # the file itself is never in the trail


def test_an_external_agents_order_is_logged_under_its_key(agent):
    offers = call(agent, "get_offers", **{**NEED, "amount": 100})
    q = call(agent, "create_quote", offer_id=offers["options"][0]["offer_id"])
    o = call(agent, "place_order", quote_id=q["quote_id"])
    assert o["status"] == "requires_escalation"
    ev = timeline(session_for(agent, "head_chef"), o["order_id"])["events"]
    assert [(e["action"], e["channel"], e["actor_id"]) for e in ev] == [
        ("quote.create", "mcp", "test-agent"),
        ("order.place", "mcp", "test-agent"),
    ]
    assert ev[-1]["inputs"]["confirmation"] == "this place_order call"  # its own call is its confirmation (M8.1)
    assert ev[-1]["reasons"][-1].startswith("MANDATE_REQUIRES_APPROVAL")


def test_imports_and_cancellations_are_logged(chef):
    imported(chef, CSV)
    q = quote_for(chef, 1000)
    o = order(chef, q["quote_id"])
    chef.post(f"/v1/orders/{o['order_id']}/cancel", json={"reason": "väärä päivä"})
    actions = [json.loads(e)["action"] for _, e, _ in rows(chef)]
    assert actions[0] == "basket.import" and actions[-1] == "order.cancel"
    last = json.loads(rows(chef)[-1][1])
    assert (last["decision"], last["inputs"]) == ("canceled", {"reason": "väärä päivä"})


def test_an_unanswered_approval_expires_into_the_trail(chef, settings):
    o = order(chef, quote_for(chef, 1000)["quote_id"])
    settings.as_of = "2026-11-15T16:00:00+02:00"  # decide_by
    assert chef.get(f"/v1/orders/{o['order_id']}").json()["status"] == "canceled"
    ev = timeline(chef, o["order_id"])["events"]
    assert (ev[-1]["action"], ev[-1]["channel"], ev[-1]["actor_id"]) == ("approval.expire", "gateway", "gateway")
    assert ev[-1]["reason_code"] == "quote_expired"
    assert [e["action"] for e in ev].count("approval.expire") == 1  # later reads add nothing


def test_no_secret_reaches_the_trail(chef):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    h = voice_headers(s)
    q = quote_for(chef)
    chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers={**h, "Idempotency-Key": "client-key-1"})
    dump = json.dumps(rows(chef))
    for secret in (PLATFORM_KEY, s["session_token"], "client-key-1"):
        assert secret not in dump
    assert signing.sha256_hex("client-key-1") in dump  # the idempotency key only as its hash


# ---- M10.1 append-only and tamper-evident -------------------------------------------------------


def test_the_trail_verifies_and_rows_cannot_be_changed_in_place(chef):
    order(chef, quote_for(chef)["quote_id"])
    r = chef.get("/v1/audit/verify").json()
    assert (r["status"], r["ok"], r["count"], r["first_broken_seq"]) == ("ok", True, 3, None)
    assert r["head_hash"] == rows(chef)[-1][2]
    with sqlite3.connect(chef.app.state.store.path) as db, pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE audit_event SET entry = '{}' WHERE seq = 1")
    with sqlite3.connect(chef.app.state.store.path) as db, pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM audit_event WHERE seq = 1")


def test_editing_any_audit_row_breaks_verification(chef):
    order(chef, quote_for(chef)["quote_id"])
    original = rows(chef)
    for seq, entry, h in original:
        body = json.loads(entry)
        edits = [
            ("UPDATE audit_event SET entry = ? WHERE seq = ?", json.dumps({**body, "decision": "x"}), seq),
            ("UPDATE audit_event SET hash = ? WHERE seq = ?", "f" * 64, seq),
            ("UPDATE audit_event SET order_id = ? WHERE seq = ?", "O-FORGED", seq),
        ]
        for sql, *args in edits:
            tamper(chef, sql, *args)
            r = chef.get("/v1/audit/verify").json()
            assert (r["ok"], r["first_broken_seq"]) == (False, seq), (sql, r)
            tamper(chef, "UPDATE audit_event SET entry = ?, hash = ?, order_id = ? WHERE seq = ?", entry, h,
                   body.get("order_id"), seq)  # fmt: skip
            assert chef.get("/v1/audit/verify").json()["ok"] is True
    tamper(chef, "DELETE FROM audit_event WHERE seq = 2")
    r = chef.get("/v1/audit/verify").json()
    assert (r["ok"], r["first_broken_seq"]) == (False, 3)


def test_a_rehashed_edit_still_breaks_the_link_to_the_next_entry(chef):
    order(chef, quote_for(chef)["quote_id"])
    seq, entry, _ = rows(chef)[0]
    forged = {**json.loads(entry), "actor": "Someone else"}
    tamper(chef, "UPDATE audit_event SET entry = ?, hash = ? WHERE seq = ?", signing.canonical(forged).decode(),
           signing.sha256_hex(signing.canonical(forged)), seq)  # fmt: skip
    r = chef.get("/v1/audit/verify").json()
    assert (r["ok"], r["first_broken_seq"]) == (False, 2)
    o = next(iter(chef.app.state.stubs.orders))
    assert timeline(chef, o)["chain_ok"] is False


def test_verify_needs_a_session(client):
    assert client.get("/v1/audit/verify").status_code == 401


# ---- who may read an order's timeline -----------------------------------------------------------


def test_the_order_audit_is_404_for_another_buyer(chef, head, monkeypatch):
    o = order(chef, quote_for(chef)["quote_id"])
    monkeypatch.setitem(identity.BUYERS, "chef_b", Buyer("chef_b", "Chef B", "p-b", "kitchen-42", "m", "buyer", "0"))
    monkeypatch.setitem(identity.BUYERS, "far", Buyer("far", "Far away", "p-f", "kitchen-7", "m", "approver", "0"))
    assert session_for(chef, "chef_b").get(f"/v1/orders/{o['order_id']}/audit").status_code == 404
    assert session_for(chef, "far").get(f"/v1/orders/{o['order_id']}/audit").status_code == 404
    assert head.get(f"/v1/orders/{o['order_id']}/audit").status_code == 200  # an approver of the same org
    assert chef.get("/v1/orders/O-NOPE/audit").status_code == 404
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    voice_only = TestClient(chef.app)
    assert voice_only.get(f"/v1/orders/{o['order_id']}/audit", headers=voice_headers(s)).status_code == 401


# ---- M10.3 the post-call webhook links the transcript --------------------------------------------


def test_the_post_call_webhook_links_the_transcript_to_the_calls_orders(chef):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    h = voice_headers(s)
    q = quote_for(chef)
    o = chef.post("/v1/orders", json={"quote_id": q["quote_id"]}, headers=h).json()
    payload = json.loads(json.dumps(PAYLOAD))
    payload["data"]["conversation_id"] = s["conversation_id"]
    raw = json.dumps(payload).encode()
    for _ in range(2):  # a retry links nothing twice
        assert chef.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": sign(raw)}).is_success
    ev = timeline(chef, o["order_id"])["events"]
    links = [e for e in ev if e["action"] == "call.transcript"]
    assert len(links) == 1 and links[0]["conversation_id"] == s["conversation_id"]
    assert links[0]["inputs"]["event_type"] == "post_call_transcription"
    stored = chef.app.state.store.conversation(s["conversation_id"])
    assert links[0]["response_sha256"] == [signing.sha256_hex(signing.canonical(stored))]  # the redacted payload
    assert "very-secret" not in json.dumps(rows(chef))


def test_a_forged_post_call_webhook_links_nothing(chef):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    o = chef.post("/v1/orders", json={"quote_id": quote_for(chef)["quote_id"]}, headers=voice_headers(s)).json()
    raw = json.dumps({**PAYLOAD, "data": {**PAYLOAD["data"], "conversation_id": s["conversation_id"]}}).encode()
    r = chef.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": sign(raw, secret="nope")})
    assert r.status_code == 401
    assert "call.transcript" not in [e["action"] for e in timeline(chef, o["order_id"])["events"]]
