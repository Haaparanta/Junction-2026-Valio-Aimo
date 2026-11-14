"""Who is calling. Identity never comes from tool arguments (PLAN §5, M7.4).

* Voice (ElevenLabs webhook tools): X-Gateway-Key (workspace secret), X-Conversation-Id
  (system__conversation_id) and X-Session-Token (secret__session_token), checked against the stored binding.
* Web (buyer UI): the demo login cookie.
"""

import hmac
import time
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException, Request

from .db import Store
from .settings import Settings, get_settings

COOKIE = "va_session"


@dataclass(frozen=True)
class Buyer:
    buyer_id: str
    display_name: str
    pseudonym: str  # sent to ElevenLabs as userId; never a real name
    org_id: str
    mandate_id: str
    role: Literal["buyer", "approver"]
    order_cap_eur: str


# Demo identities (PLAN M7.1 seeds; real mandates arrive with M7).
BUYERS: dict[str, Buyer] = {
    "chef": Buyer("chef", "Chef Aada (demo)", "buyer-7f3a", "kitchen-42", "mandate-chef-500", "buyer", "500.00"),
    "head_chef": Buyer(
        "head_chef", "Head chef Mikko (demo)", "buyer-91c2", "kitchen-42", "mandate-head-chef", "approver", "5000.00"
    ),
}


@dataclass(frozen=True)
class Caller:
    channel: Literal["voice", "web"]
    buyer: Buyer
    conversation_id: str | None = None


def get_store(request: Request) -> Store:
    return request.app.state.store


StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _fail(status: int, en: str) -> HTTPException:
    # Short, safe text: with passthrough error handling the agent may read it aloud.
    return HTTPException(status_code=status, detail=en)


def web_buyer(store: StoreDep, va_session: Annotated[str | None, Cookie()] = None) -> Buyer:
    buyer_id = store.web_session_buyer(va_session) if va_session else None
    if buyer_id is None or buyer_id not in BUYERS:
        raise _fail(401, "Please sign in first.")
    return BUYERS[buyer_id]


def voice_caller(
    store: StoreDep,
    settings: SettingsDep,
    x_gateway_key: Annotated[str, Header()],
    x_conversation_id: Annotated[str, Header()],
    x_session_token: Annotated[str, Header()],
) -> Caller:
    key = settings.gateway_platform_key
    if not key or not hmac.compare_digest(x_gateway_key.encode(), key.encode()):
        raise _fail(401, "Unknown caller.")
    s = store.voice_session(x_session_token)
    if s is None or s.revoked or s.expires_at < time.time():
        raise _fail(401, "This call has expired. Please start a new call.")
    if s.conversation_id is None:  # signed-URL (WebSocket) session: bind on first use
        s = store.bind_conversation_once(x_session_token, x_conversation_id)
    if s is None or s.conversation_id != x_conversation_id:
        raise _fail(403, "This call is not linked to your session.")
    buyer = BUYERS.get(s.buyer_id)
    if buyer is None:
        raise _fail(403, "This call is not linked to your session.")
    return Caller("voice", buyer, s.conversation_id)


def any_caller(
    store: StoreDep,
    settings: SettingsDep,
    x_gateway_key: Annotated[str | None, Header()] = None,
    x_conversation_id: Annotated[str | None, Header()] = None,
    x_session_token: Annotated[str | None, Header()] = None,
    va_session: Annotated[str | None, Cookie()] = None,
) -> Caller:
    """Webhook tools (voice headers) or the buyer UI (cookie). The voice path wins if its key is present."""
    if x_gateway_key is not None:
        if not x_conversation_id or not x_session_token:
            raise _fail(401, "Unknown caller.")
        return voice_caller(store, settings, x_gateway_key, x_conversation_id, x_session_token)
    return Caller("web", web_buyer(store, va_session))


CallerDep = Annotated[Caller, Depends(any_caller)]
WebBuyerDep = Annotated[Buyer, Depends(web_buyer)]
