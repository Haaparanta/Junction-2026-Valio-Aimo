"""Gateway settings, read from the environment and git-ignored env files (names in .env.example)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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

    # Claude (docs/basket-plan.md B-08). The key is optional: without it the SDK reads ANTHROPIC_AUTH_TOKEN or the
    # `ant auth login` profile itself. It is only ever handed to the Anthropic SDK, never to the browser or a response.
    anthropic_api_key: str | None = None
    vision_model: str = "claude-opus-5-5"  # reads photos of shopping lists (M28)
    dish_model: str = "claude-opus-5-5"  # breaks a dish down into ingredients (M26, M27)

    public_host: str | None = None  # e.g. abcd.ngrok-free.app, without scheme
    db_path: Path = Field(default=REPO_ROOT / "data" / "gateway.db")
    session_ttl_s: int = 1800  # opaque voice session token lifetime (PLAN M14.2)
    web_session_ttl_s: int = 12 * 3600
    # Demo as-of clock (PLAN M3.3): every Monday cut-off has passed after Sun 15.11 17:00.
    as_of: str = "2026-11-14T10:00:00+02:00"
    cookie_secure: bool = False  # True behind HTTPS in production
    web_dist: Path | None = Field(default=REPO_ROOT / "web" / "dist")  # built UI served at / when present

    # External AI agents over MCP (PLAN M12.2): agent name -> SHA-256 hex of its bearer key, never the key itself.
    # MCP_AGENT_KEYS='{"claude-code": "<sha256 hex>"}'. Every key maps to the external-agent mandate (quote only).
    mcp_agent_keys: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    # Host and Origin allowlists of /mcp (DNS-rebinding protection); PUBLIC_HOST is added to both at startup.
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    )
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    )

    @field_validator("mcp_agent_keys", "mcp_allowed_hosts", "mcp_allowed_origins", mode="before")
    @classmethod
    def _json_or_default(cls, v: Any, info: Any) -> Any:
        """JSON from the environment; an empty value (as copied from .env.example) keeps the default."""
        if isinstance(v, str):
            if not v.strip():
                return cls.model_fields[info.field_name].get_default(call_default_factory=True)
            return json.loads(v)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
