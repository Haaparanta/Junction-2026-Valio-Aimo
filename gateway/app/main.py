"""App factory. Run: uv run uvicorn app.main:app --app-dir gateway --port 8000"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import session, tools, webhooks
from .db import Store
from .settings import Settings, get_settings
from .stubs import StubState

DESCRIPTION = """Agent gateway for Valio Aimo buyers and their AI agents.

The LLM plans and explains; this gateway decides. Every tool answers HTTP 200 with a `status`
(UCP checkout statuses for quotes, orders and approvals, `ok` otherwise), a `reason_code`,
`message_for_user` in Finnish and English, and `warnings[]`. **Contract stubs (M1.6):** answers are
canned from the headline example W-03 until the real services land."""


def create_app(settings: Settings | None = None, voice: session.VoiceProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Valio Aimo agent gateway", version="0.1.0", description=DESCRIPTION)
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.store = Store(settings.db_path)
    app.state.stubs = StubState()
    app.state.voice = voice or session.ElevenLabsVoice(settings)

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok", "as_of": settings.as_of, "mode": "stub"}

    app.include_router(tools.router)
    app.include_router(session.router)
    app.include_router(webhooks.router)
    if settings.web_dist and (settings.web_dist / "index.html").is_file():
        # Production: the built buyer UI from the same origin (cookies, HTTPS for the microphone). Mounted last.
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")
    return app


app = create_app()
