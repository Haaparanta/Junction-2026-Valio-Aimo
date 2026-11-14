"""Gateway settings, read from the environment and git-ignored env files (names in .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win. .env.local holds the ElevenLabs key (written by the ElevenLabs onboarding);
        # .env.gateway holds the gateway's own generated secrets (scripts/gen_secrets.py).
        env_file=(REPO_ROOT / ".env", REPO_ROOT / ".env.local", REPO_ROOT / ".env.gateway"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ElevenLabs. In the cloud sandbox the proxy injects xi-api-key, so the key may be unset.
    elevenlabs_api_key: str | None = None
    elevenlabs_agent_id: str | None = None
    elevenlabs_webhook_secret: str | None = None  # HMAC secret of the post-call webhook
    # Shared secret sent by every webhook tool as X-Gateway-Key; also stored as an ElevenLabs workspace secret.
    gateway_platform_key: str | None = None

    public_host: str | None = None  # e.g. abcd.ngrok-free.app, without scheme
    db_path: Path = Field(default=REPO_ROOT / "data" / "gateway.db")
    session_ttl_s: int = 1800  # opaque voice session token lifetime (PLAN M14.2)
    web_session_ttl_s: int = 12 * 3600
    # Demo as-of clock (PLAN M3.3): every Monday cut-off has passed after Sun 15.11 17:00.
    as_of: str = "2026-11-14T10:00:00+02:00"
    cookie_secure: bool = False  # True behind HTTPS in production
    web_dist: Path | None = Field(default=REPO_ROOT / "web" / "dist")  # built UI served at / when present


@lru_cache
def get_settings() -> Settings:
    return Settings()
