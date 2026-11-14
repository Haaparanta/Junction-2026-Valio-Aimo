"""Demo buyer login and POST /api/agent-session (PLAN M14.2). The ElevenLabs key never reaches the browser."""

from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..identity import BUYERS, COOKIE, SettingsDep, StoreDep, WebBuyerDep
from ..settings import Settings

router = APIRouter(prefix="/api", tags=["session"])


class VoiceProvider(Protocol):
    def webrtc_token(self) -> tuple[str, str]: ...  # (conversation token, conversation id)
    def signed_url(self) -> str: ...


class VoiceUnavailable(Exception):
    pass


class ElevenLabsVoice:
    """Mints private-agent credentials with the ElevenLabs SDK (sync client, so routes run on a worker thread)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self):  # imported lazily: tests never touch the network
        from elevenlabs import ElevenLabs

        # In the cloud sandbox the proxy injects xi-api-key, so a placeholder is enough there.
        return ElevenLabs(api_key=self.settings.elevenlabs_api_key or "proxy-injected", timeout=10)

    def _agent(self) -> str:
        if not self.settings.elevenlabs_agent_id:
            raise VoiceUnavailable("ELEVENLABS_AGENT_ID is not set; run agent/provision.py")
        return self.settings.elevenlabs_agent_id

    def webrtc_token(self) -> tuple[str, str]:
        try:
            r = self._client().conversational_ai.conversations.get_webrtc_token(agent_id=self._agent())
        except VoiceUnavailable:
            raise
        except Exception as e:  # SDK raises ApiError and httpx errors
            raise VoiceUnavailable(type(e).__name__) from e
        return r.token, r.conversation_id

    def signed_url(self) -> str:
        try:
            r = self._client().conversational_ai.conversations.get_signed_url(agent_id=self._agent())
        except VoiceUnavailable:
            raise
        except Exception as e:
            raise VoiceUnavailable(type(e).__name__) from e
        return r.signed_url


def get_voice(request: Request) -> VoiceProvider:
    return request.app.state.voice


class LoginRequest(BaseModel):
    buyer_id: Literal["chef", "head_chef"] = "chef"


class Me(BaseModel):
    buyer_id: str
    display_name: str
    org_id: str
    role: str
    order_cap_eur: str
    as_of: str


@router.post("/login")
def login(body: LoginRequest, response: Response, store: StoreDep, settings: SettingsDep) -> Me:
    buyer = BUYERS[body.buyer_id]
    token = store.create_web_session(buyer.buyer_id, settings.web_session_ttl_s)
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.web_session_ttl_s,
        path="/",
    )
    return Me(
        buyer_id=buyer.buyer_id,
        display_name=buyer.display_name,
        org_id=buyer.org_id,
        role=buyer.role,
        order_cap_eur=buyer.order_cap_eur,
        as_of=settings.as_of,
    )


@router.post("/logout", status_code=204)
def logout(response: Response, store: StoreDep, va_session: Annotated[str | None, Cookie()] = None) -> None:
    if va_session:
        store.delete_web_session(va_session)
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
def me(buyer: WebBuyerDep, settings: SettingsDep) -> Me:
    return Me(
        buyer_id=buyer.buyer_id,
        display_name=buyer.display_name,
        org_id=buyer.org_id,
        role=buyer.role,
        order_cap_eur=buyer.order_cap_eur,
        as_of=settings.as_of,
    )


class AgentSessionRequest(BaseModel):
    mode: Literal["webrtc", "websocket"] = Field(
        default="webrtc", description="webrtc (conversation token) by default; websocket (signed URL) as a fallback."
    )


class AgentSessionResponse(BaseModel):
    mode: Literal["webrtc", "websocket"]
    conversation_token: str | None = None
    signed_url: str | None = None
    conversation_id: str | None = None  # known up front for WebRTC; bound on the first tool call for WebSocket
    session_token: str  # pass as the dynamic variable secret__session_token; it reaches tool headers only
    user_id: str  # pseudonym for ElevenLabs analytics, never used for auth
    expires_in: int


@router.post("/agent-session")
def agent_session(
    body: AgentSessionRequest,
    buyer: WebBuyerDep,
    store: StoreDep,
    settings: SettingsDep,
    voice: Annotated[VoiceProvider, Depends(get_voice)],
) -> AgentSessionResponse:
    try:
        if body.mode == "webrtc":
            token, conversation_id = voice.webrtc_token()
            signed_url = None
        else:
            token, conversation_id, signed_url = None, None, voice.signed_url()
    except VoiceUnavailable as e:
        raise HTTPException(502, f"voice service unavailable ({e})") from e
    session_token = store.create_voice_session(
        buyer_id=buyer.buyer_id,
        org_id=buyer.org_id,
        mandate_id=buyer.mandate_id,
        conversation_id=conversation_id,
        mode=body.mode,
        ttl_s=settings.session_ttl_s,
    )
    # M10: write an audit row here once the hash-chained log exists.
    return AgentSessionResponse(
        mode=body.mode,
        conversation_token=token,
        signed_url=signed_url,
        conversation_id=conversation_id,
        session_token=session_token,
        user_id=buyer.pseudonym,
        expires_in=settings.session_ttl_s,
    )
