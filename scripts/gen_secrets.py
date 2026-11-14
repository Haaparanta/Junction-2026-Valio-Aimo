#!/usr/bin/env python3
"""Create the gateway's own secrets in the git-ignored .env.gateway, once. Values are never printed."""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envfile import has_value, set_values  # noqa: E402

TARGET = Path(__file__).resolve().parent.parent / ".env.gateway"

if __name__ == "__main__":
    if has_value(TARGET, "GATEWAY_PLATFORM_KEY"):
        print(".env.gateway already has GATEWAY_PLATFORM_KEY; left unchanged")
    else:
        set_values(TARGET, {"GATEWAY_PLATFORM_KEY": secrets.token_urlsafe(32)})
        print("wrote GATEWAY_PLATFORM_KEY to .env.gateway (git-ignored)")
