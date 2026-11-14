import pytest
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient

PLATFORM_KEY = "test-platform-key"
WEBHOOK_SECRET = "test-webhook-secret"


class FakeVoice:
    """Stands in for ElevenLabs token minting."""

    def __init__(self) -> None:
        self.n = 0

    def webrtc_token(self) -> tuple[str, str]:
        self.n += 1
        return f"tok-{self.n}", f"conv_{self.n}"

    def signed_url(self) -> str:
        return "wss://example.invalid/signed"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "gw.db",
        gateway_platform_key=PLATFORM_KEY,
        elevenlabs_webhook_secret=WEBHOOK_SECRET,
        elevenlabs_agent_id="agent_test",
    )


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings, voice=FakeVoice()))


@pytest.fixture
def chef(client) -> TestClient:
    assert client.post("/api/login", json={"buyer_id": "chef"}).status_code == 200
    return client


def voice_headers(session: dict) -> dict:
    return {
        "X-Gateway-Key": PLATFORM_KEY,
        "X-Conversation-Id": session["conversation_id"],
        "X-Session-Token": session["session_token"],
    }
