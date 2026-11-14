from datetime import date

import pytest
from app.contract import DishBreakdown, DishInput, ListExtraction
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


def sample_breakdown(inp: DishInput) -> DishBreakdown:
    """What FakeLLM plans for any dish unless told otherwise: whipping cream, already within the B-12 rules."""
    return DishBreakdown.model_validate(
        {
            "dish": inp.dish,
            "dish_name": {"fi": inp.dish, "en": inp.dish},
            "servings": inp.servings,
            "batch_note": {"fi": "Testisuunnitelma.", "en": "A test plan."},
            "ingredients": [
                {
                    "ingredient_id": "kerma",
                    "name": {"fi": "kuohukerma", "en": "whipping cream"},
                    "role": "main",
                    "amount": round(0.1 * inp.servings, 3),
                    "unit": "L",
                    "per_serving": 0.1,
                    "search": {
                        "query": "kuohukerma",
                        "heads": ["kerma", "kuohukerma"],
                        "exclude": ["kasvirasva"],
                        "must_claims": [c for c in inp.must_claims if c in ("FREE_FROM_LACTOSE", "LOW_LACTOSE")],
                        "must_not_allergens": list(inp.must_not_allergens),
                        "temperature": "chilled",
                        "limit": 10,
                    },
                    "need_date": inp.need_date,
                    "notes": [],
                }
            ],
            "assumptions": [],
            "warnings": [],
        }
    )


class FakeLLM:
    """Stands in for Claude (app/llm.py): canned answers, or the failure a test sets.

    `extraction` is what read_list returns; `dish` is what breakdown returns (None: sample_breakdown of the input).
    Set `error` to an LLMUnavailable or LLMRefused instance to make both calls raise it. `calls` records each call.
    """

    def __init__(
        self,
        extraction: ListExtraction | None = None,
        dish: DishBreakdown | None = None,
        error: Exception | None = None,
    ) -> None:
        self.extraction = extraction or ListExtraction(items=[], handwritten=False, unreadable=[], need_date=None)
        self.dish = dish
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def read_list(self, image: bytes, media_type: str, today: date) -> ListExtraction:
        self.calls.append(("read_list", media_type))
        if self.error is not None:
            raise self.error
        return self.extraction

    def breakdown(self, inp: DishInput) -> DishBreakdown:
        self.calls.append(("breakdown", inp))
        if self.error is not None:
            raise self.error
        return self.dish if self.dish is not None else sample_breakdown(inp)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "gw.db",
        gateway_platform_key=PLATFORM_KEY,
        elevenlabs_webhook_secret=WEBHOOK_SECRET,
        elevenlabs_agent_id="agent_test",
        web_dist=None,
    )


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings, voice=FakeVoice(), llm=FakeLLM()))


@pytest.fixture
def llm(client) -> FakeLLM:
    """The client's FakeLLM, to set its answers or its error."""
    return client.app.state.llm


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
