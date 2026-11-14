"""M14.2: session endpoint and webhook-tool auth (X-Gateway-Key, X-Conversation-Id, X-Session-Token)."""

from conftest import PLATFORM_KEY, voice_headers

NEED = {"query": "maito", "amount": 10, "unit": "L", "need_date": "2026-11-16"}


def test_agent_session_needs_login(client):
    assert client.post("/api/agent-session", json={}).status_code == 401


def test_session_response_has_no_elevenlabs_key(chef):
    s = chef.post("/api/agent-session", json={"mode": "webrtc"}).json()
    assert set(s) == {
        "mode",
        "conversation_token",
        "signed_url",
        "conversation_id",
        "session_token",
        "user_id",
        "expires_in",
    }
    assert s["user_id"].startswith("buyer-") and "Aada" not in s["user_id"]


def test_valid_voice_call_passes(chef):
    s = chef.post("/api/agent-session", json={}).json()
    chef.cookies.clear()  # webhook tools carry no cookie
    assert chef.post("/v1/offers", json=NEED, headers=voice_headers(s)).status_code == 200


def test_wrong_platform_key_is_401(chef):
    s = chef.post("/api/agent-session", json={}).json()
    chef.cookies.clear()
    h = {**voice_headers(s), "X-Gateway-Key": "nope"}
    assert chef.post("/v1/offers", json=NEED, headers=h).status_code == 401


def test_missing_session_token_is_401(chef):
    chef.cookies.clear()
    h = {"X-Gateway-Key": PLATFORM_KEY, "X-Conversation-Id": "conv_1"}
    assert chef.post("/v1/offers", json=NEED, headers=h).status_code == 401


def test_unknown_session_token_is_401(chef):
    chef.cookies.clear()
    h = {"X-Gateway-Key": PLATFORM_KEY, "X-Conversation-Id": "conv_1", "X-Session-Token": "forged"}
    assert chef.post("/v1/offers", json=NEED, headers=h).status_code == 401


def test_other_conversation_is_403(chef):
    s = chef.post("/api/agent-session", json={}).json()
    chef.cookies.clear()
    h = {**voice_headers(s), "X-Conversation-Id": "conv_somebody_else"}
    r = chef.post("/v1/offers", json=NEED, headers=h)
    assert r.status_code == 403 and r.json()["detail"]


def test_signed_url_session_binds_once(chef):
    s = chef.post("/api/agent-session", json={"mode": "websocket"}).json()
    assert s["signed_url"] and s["conversation_id"] is None and s["conversation_token"] is None
    chef.cookies.clear()
    h = {"X-Gateway-Key": PLATFORM_KEY, "X-Conversation-Id": "conv_ws_1", "X-Session-Token": s["session_token"]}
    assert chef.post("/v1/offers", json=NEED, headers=h).status_code == 200
    assert chef.post("/v1/offers", json=NEED, headers=h).status_code == 200
    h2 = {**h, "X-Conversation-Id": "conv_ws_2"}
    assert chef.post("/v1/offers", json=NEED, headers=h2).status_code == 403


def test_expired_session_is_401(chef, settings):
    settings.session_ttl_s = -1
    s = chef.post("/api/agent-session", json={}).json()
    chef.cookies.clear()
    assert chef.post("/v1/offers", json=NEED, headers=voice_headers(s)).status_code == 401


def test_platform_key_unset_fails_closed(chef, settings):
    s = chef.post("/api/agent-session", json={}).json()
    chef.cookies.clear()
    settings.gateway_platform_key = None
    assert chef.post("/v1/offers", json=NEED, headers=voice_headers(s)).status_code == 401
