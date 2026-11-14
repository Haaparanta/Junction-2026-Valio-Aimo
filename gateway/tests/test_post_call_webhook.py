"""M10.3: the post-call webhook verifies its HMAC and redacts secret__ values."""

import hashlib
import hmac
import json
import time

from app.api.webhooks import verify_signature
from conftest import WEBHOOK_SECRET

PAYLOAD = {
    "type": "post_call_transcription",
    "event_timestamp": 1,
    "data": {
        "agent_id": "agent_test",
        "conversation_id": "conv_42",
        "status": "done",
        "transcript": [{"role": "user", "message": "Tarvitsen tuhat litraa laktoositonta maitoa"}],
        "conversation_initiation_client_data": {
            "dynamic_variables": {"secret__session_token": "very-secret", "system__conversation_id": "conv_42"}
        },
    },
}


def sign(raw: bytes, ts: int | None = None, secret: str = WEBHOOK_SECRET) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},v0={mac}"


def test_valid_signature_is_stored_and_redacted(client):
    raw = json.dumps(PAYLOAD).encode()
    r = client.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": sign(raw)})
    assert r.status_code == 200
    stored = client.app.state.store.conversation("conv_42")
    dv = stored["conversation_initiation_client_data"]["dynamic_variables"]
    assert dv["secret__session_token"] == "<redacted>" and dv["system__conversation_id"] == "conv_42"
    assert "very-secret" not in json.dumps(stored)


def test_retry_upserts(client):
    raw = json.dumps(PAYLOAD).encode()
    for _ in range(2):
        assert client.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": sign(raw)}).is_success


def test_forged_signature_is_401(client):
    raw = json.dumps(PAYLOAD).encode()
    bad = sign(raw, secret="attacker")
    assert client.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": bad}).status_code == 401


def test_tampered_body_is_401(client):
    raw = json.dumps(PAYLOAD).encode()
    sig = sign(raw)
    tampered = raw.replace(b"conv_42", b"conv_43")
    assert (
        client.post("/webhooks/elevenlabs", content=tampered, headers={"ElevenLabs-Signature": sig}).status_code == 401
    )


def test_stale_signature_is_401(client):
    raw = json.dumps(PAYLOAD).encode()
    old = sign(raw, ts=int(time.time()) - 1801)
    assert client.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": old}).status_code == 401


def test_missing_signature_is_401(client):
    assert client.post("/webhooks/elevenlabs", content=b"{}").status_code == 401


def test_verify_signature_edge_cases():
    raw = b"{}"
    now = 1_800_000_000
    good = sign(raw, ts=now)
    assert verify_signature(WEBHOOK_SECRET, good, raw, now=now + 1799)
    assert not verify_signature(WEBHOOK_SECRET, good, raw, now=now + 1801)
    assert not verify_signature(WEBHOOK_SECRET, "t=abc,v0=00", raw, now=now)
    assert not verify_signature(WEBHOOK_SECRET, "", raw, now=now)


def test_unconfigured_secret_fails_closed(client, settings):
    settings.elevenlabs_webhook_secret = None
    raw = json.dumps(PAYLOAD).encode()
    assert (
        client.post("/webhooks/elevenlabs", content=raw, headers={"ElevenLabs-Signature": sign(raw)}).status_code == 503
    )
