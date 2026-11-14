"""ElevenLabs post-call webhook (PLAN M10.3): HMAC over "t.body", 30-minute tolerance, secrets redacted."""

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..identity import SettingsDep, StoreDep

router = APIRouter(tags=["webhooks"])
TOLERANCE_S = 1800
REDACTED = "<redacted>"


def verify_signature(secret: str, header: str, raw: bytes, now: float | None = None) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t", "").strip(), parts.get("v0", "").strip()
    if not ts.isdigit() or not sig:
        return False
    if abs((now if now is not None else time.time()) - int(ts)) > TOLERANCE_S:
        return False
    mac = hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig)


def redact(obj: Any) -> Any:
    """secret__ dynamic variables arrive in clear in post-call payloads: never store them."""
    if isinstance(obj, dict):
        return {k: (REDACTED if isinstance(k, str) and k.startswith("secret__") else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


@router.post("/webhooks/elevenlabs")
async def post_call(request: Request, store: StoreDep, settings: SettingsDep) -> dict:
    secret = settings.elevenlabs_webhook_secret
    if not secret:
        raise HTTPException(503, "post-call webhook secret not configured")
    raw = await request.body()  # verify the raw bytes before parsing
    if not verify_signature(secret, request.headers.get("elevenlabs-signature", ""), raw):
        raise HTTPException(401, "bad signature")
    try:
        event = json.loads(raw)
        data = event["data"]
        conversation_id = data["conversation_id"]
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, "unexpected payload") from e
    event_type = str(event.get("type", "unknown"))
    clean = redact(data)
    if event_type != "post_call_transcription":  # audio and failure events: keep metadata only
        clean = {k: clean.get(k) for k in ("conversation_id", "agent_id", "status", "failure_reason") if k in clean}
    # Retries resend the same payload, so upsert by conversation id. M10 links it to orders and the audit chain.
    store.upsert_conversation(conversation_id, data.get("agent_id"), event_type, clean)
    return {"ok": True}
