#!/usr/bin/env python3
"""ElevenLabs agent as code (PLAN M13).

    uv run python agent/provision.py tools            # write tool_configs/*.json from the gateway's OpenAPI
    uv run python agent/provision.py tools --check    # CI: fail if tool_configs/ is stale
    uv run python agent/provision.py build            # print the full agent JSON that push would send
    uv run python agent/provision.py push --host abcd.ngrok-free.app

ElevenLabs has no OpenAPI import, so webhook tools are generated from the gateway's operations tagged
"agent-tools" (operationId = tool name, `x-agent-tool` = voice settings). Every webhook tool sends three
headers the LLM never fills: X-Gateway-Key (workspace secret), X-Conversation-Id (system__conversation_id)
and X-Session-Token (secret__session_token). URLs use the workspace environment variable gateway_host.

`push` is idempotent: it upserts the workspace secret, the gateway_host variable, the post-call HMAC webhook
and the agent, and records the agent id and webhook secret in the git-ignored .env.gateway. It creates the
agent but starts no conversation, so it spends no conversation credits. No value is ever printed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path[:0] = [str(REPO / "gateway"), str(REPO / "scripts")]

TOOL_DIR = HERE / "tool_configs"
CLIENT_DIR = HERE / "client_tools"
AGENT_FILE = HERE / "agent_configs" / "aino.json"
PROMPT_FILE = HERE / "prompt" / "aino.md"
ENV_GATEWAY = REPO / ".env.gateway"
API = "https://api.elevenlabs.io"
SECRET_NAME = "gateway_platform_key"  # noqa: S105 (a name, not a value)
ENV_VAR = "gateway_host"
WEBHOOK_NAME = "valio-aimo-gateway-post-call"
SECRET_ID_PLACEHOLDER = "<gateway_platform_key secret id>"  # noqa: S105
HEADERS = {
    "X-Gateway-Key": {"secret_id": SECRET_ID_PLACEHOLDER},
    "X-Conversation-Id": {"variable_name": "system__conversation_id"},
    "X-Session-Token": {"variable_name": "secret__session_token"},
}


# ---- OpenAPI -> ElevenLabs tool schema --------------------------------------------------------


def resolve(spec: dict, schema: dict) -> dict:
    """Inline $ref and single-item allOf: how ElevenLabs treats $ref/$defs is unverified (tech-research §7)."""
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = {**spec["components"]["schemas"][name], **{k: v for k, v in schema.items() if k != "$ref"}}
    if "allOf" in schema and len(schema["allOf"]) == 1:
        schema = {**resolve(spec, schema["allOf"][0]), **{k: v for k, v in schema.items() if k != "allOf"}}
    return schema


def literal(spec: dict, s: dict, fallback_desc: str) -> dict:
    s = resolve(spec, s)
    if "anyOf" in s:
        raise ValueError(f"anyOf is not supported in agent tool schemas: {s}")
    t = s.get("type", "string")
    desc = s.get("description") or fallback_desc
    if t == "object":
        return obj(spec, s, desc)
    out: dict[str, Any] = {"type": t, "description": desc}
    if t == "array":
        out["items"] = literal(spec, s.get("items", {"type": "string"}), f"One item of: {desc}")
    if "enum" in s:
        out["enum"] = s["enum"]
    elif "const" in s:
        out["enum"] = [s["const"]]
    if "default" in s and t != "array":
        out["description"] = f"{desc} Default: {json.dumps(s['default'], ensure_ascii=False)}."
    return out


def obj(spec: dict, s: dict, desc: str) -> dict:
    s = resolve(spec, s)
    props = {k: literal(spec, v, k) for k, v in s.get("properties", {}).items()}
    out = {"type": "object", "description": desc, "properties": props}
    if s.get("required"):
        out["required"] = s["required"]
    return out


def webhook_tools(spec: dict) -> list[dict]:
    tools = []
    for path, methods in sorted(spec["paths"].items()):
        for method, op in methods.items():
            if "agent-tools" not in op.get("tags", []):
                continue
            x = op["x-agent-tool"]
            api_schema: dict[str, Any] = {
                "url": "https://{{system__env_" + ENV_VAR + "}}" + path,
                "method": method.upper(),
                "request_headers": copy.deepcopy(HEADERS),
                "response_filter": {"mode": "allow", "filters": x["response_filter"]},
            }
            path_params = {
                p["name"]: literal(spec, p["schema"], p.get("description", p["name"]))
                for p in op.get("parameters", [])
                if p["in"] == "path"
            }
            for p in op.get("parameters", []):
                if p["in"] == "path" and p.get("description"):
                    path_params[p["name"]]["description"] = p["description"]
            if path_params:
                api_schema["path_params_schema"] = path_params
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                api_schema["content_type"] = "application/json"
                api_schema["request_body_schema"] = obj(spec, body, f"Arguments for {op['operationId']}.")
            tool = {
                "type": "webhook",
                "name": op["operationId"],
                "description": x["description"],
                "response_timeout_secs": x.get("response_timeout_secs", 10),
                "tool_error_handling_mode": "passthrough",
                "pre_tool_speech": x.get("pre_tool_speech", "auto"),
                "interruption_mode": x.get("interruption_mode", "allow"),
                "api_schema": api_schema,
            }
            if "tool_call_sound" in x:
                tool["tool_call_sound"] = x["tool_call_sound"]
            tools.append(tool)
    return tools


def gateway_openapi() -> dict:
    from app.main import create_app
    from app.settings import Settings

    return create_app(Settings(_env_file=None, db_path=":memory:")).openapi()


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def cmd_tools(check: bool) -> int:
    tools = webhook_tools(gateway_openapi())
    wanted = {f"{t['name']}.json": dump(t) for t in tools}
    TOOL_DIR.mkdir(exist_ok=True)
    existing = {p.name: p.read_text() for p in TOOL_DIR.glob("*.json")}
    if check:
        if existing != wanted:
            print("agent/tool_configs is stale: run `uv run python agent/provision.py tools`", file=sys.stderr)
            return 1
        print(f"agent/tool_configs is up to date ({len(wanted)} webhook tools)")
        return 0
    for name in existing.keys() - wanted.keys():
        (TOOL_DIR / name).unlink()
    for name, text in wanted.items():
        (TOOL_DIR / name).write_text(text)
    print(f"wrote {len(wanted)} webhook tool configs to agent/tool_configs/")
    return 0


def build_agent(secret_id: str = SECRET_ID_PLACEHOLDER, webhook_id: str | None = None) -> dict:
    agent = json.loads(AGENT_FILE.read_text())
    prompt = agent["conversation_config"]["agent"]["prompt"]
    prompt["prompt"] = PROMPT_FILE.read_text()
    tools = [json.loads(p.read_text()) for p in sorted(TOOL_DIR.glob("*.json"))]
    tools += [json.loads(p.read_text()) for p in sorted(CLIENT_DIR.glob("*.json"))]
    for t in tools:
        for h in t.get("api_schema", {}).get("request_headers", {}).values():
            if isinstance(h, dict) and h.get("secret_id") == SECRET_ID_PLACEHOLDER:
                h["secret_id"] = secret_id
    prompt["tools"] = tools
    if webhook_id:
        agent["platform_settings"]["workspace_overrides"] = {
            "webhooks": {"post_call_webhook_id": webhook_id, "events": ["transcript"]}
        }
    return agent


# ---- push --------------------------------------------------------------------------------------


def cmd_push(host: str, webhook_override: str | None = None) -> int:
    import httpx
    from app.settings import Settings
    from elevenlabs import ElevenLabs
    from elevenlabs.core.api_error import ApiError
    from elevenlabs.environment_variables.types.environment_variables_create_request_body import (
        EnvironmentVariablesCreateRequestBody_String,
    )
    from elevenlabs.types.webhook_hmac_settings import WebhookHmacSettings
    from envfile import set_values

    host = host.removeprefix("https://").removeprefix("http://").rstrip("/")
    s = Settings()
    if not s.gateway_platform_key:
        sys.exit("GATEWAY_PLATFORM_KEY missing: run `python3 scripts/gen_secrets.py` first")
    key = s.elevenlabs_api_key or "proxy-injected"
    el = ElevenLabs(api_key=key)

    # 1. Workspace secret that webhook tools send as X-Gateway-Key.
    secret = next((x for x in el.conversational_ai.secrets.list().secrets if x.name == SECRET_NAME), None)
    if secret is None:
        secret_id = el.conversational_ai.secrets.create(name=SECRET_NAME, value=s.gateway_platform_key).secret_id
        print(f"created workspace secret {SECRET_NAME}")
    else:
        secret_id = secret.secret_id
        el.conversational_ai.secrets.update(secret_id, name=SECRET_NAME, value=s.gateway_platform_key)
        print(f"updated workspace secret {SECRET_NAME}")

    # 2. Environment variable gateway_host (needs a production value to resolve).
    var = next(
        (v for v in el.environment_variables.list(label=ENV_VAR).environment_variables if v.label == ENV_VAR), None
    )
    if var is None:
        el.environment_variables.create(
            request=EnvironmentVariablesCreateRequestBody_String(
                type="string", label=ENV_VAR, values={"production": host}
            )
        )
        print(f"created environment variable {ENV_VAR}={host}")
    else:
        el.environment_variables.update(var.id, values={"production": host})
        print(f"updated environment variable {ENV_VAR}={host}")

    # 3. Post-call HMAC webhook. Its URL cannot be edited, so a host change recreates it (and its secret).
    url = f"https://{host}/webhooks/elevenlabs"
    webhook_id: str | None = None
    try:
        hooks = [w for w in el.webhooks.list().webhooks if w.name == WEBHOOK_NAME]
        hook = next((w for w in hooks if w.webhook_url == url), None)
        if hook is not None and s.elevenlabs_webhook_secret:
            webhook_id = hook.webhook_id
            print("post-call webhook unchanged")
        else:
            for w in hooks:
                el.webhooks.delete(w.webhook_id)
            created = el.webhooks.create(
                settings=WebhookHmacSettings(auth_type="hmac", name=WEBHOOK_NAME, webhook_url=url)
            )
            webhook_id = created.webhook_id
            set_values(ENV_GATEWAY, {"ELEVENLABS_WEBHOOK_SECRET": created.webhook_secret})
            print(f"created post-call webhook -> {url} (secret saved to .env.gateway)")
    except ApiError as e:
        if e.status_code not in (401, 403):
            raise
        print(
            "skipped the post-call webhook: this API key lacks webhooks_write. Create an HMAC webhook named "
            f"{WEBHOOK_NAME} for {url} in the ElevenLabs dashboard (Settings > Webhooks), save its secret as "
            "ELEVENLABS_WEBHOOK_SECRET in .env.gateway, and rerun push with --webhook-id <id>.",
            file=sys.stderr,
        )
    webhook_id = webhook_id or webhook_override

    # 4. The agent, as raw API JSON (read-modify-write: partial PATCH merging is unverified, EL-13).
    body = build_agent(secret_id, webhook_id)
    headers = {"xi-api-key": key}
    with httpx.Client(base_url=API, headers=headers, timeout=30) as http:
        agent_id = s.elevenlabs_agent_id
        if agent_id and http.get(f"/v1/convai/agents/{agent_id}").status_code == 404:
            agent_id = None
        if agent_id:
            r = http.patch(f"/v1/convai/agents/{agent_id}", json=body)
            action = "updated"
        else:
            r = http.post("/v1/convai/agents/create", json=body)
            action = "created"
        if r.status_code >= 400:
            print(f"agent {action[:-1]} failed: HTTP {r.status_code}\n{r.text[:2000]}", file=sys.stderr)
            return 1
        agent_id = agent_id or r.json()["agent_id"]
    set_values(ENV_GATEWAY, {"ELEVENLABS_AGENT_ID": agent_id, "PUBLIC_HOST": host})
    print(f"{action} agent {agent_id}; dashboard: https://elevenlabs.io/app/agents/agents/{agent_id}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tools", help="write tool_configs/ from the gateway OpenAPI")
    t.add_argument("--check", action="store_true", help="fail if tool_configs/ is stale")
    sub.add_parser("build", help="print the agent JSON push would send")
    p = sub.add_parser("push", help="create or update the agent and its workspace resources")
    p.add_argument("--host", required=True, help="public gateway host, e.g. abcd.ngrok-free.app")
    p.add_argument("--webhook-id", help="id of a post-call HMAC webhook created in the dashboard")
    args = ap.parse_args()
    if args.cmd == "tools":
        return cmd_tools(args.check)
    if args.cmd == "build":
        sys.stdout.write(dump(build_agent()))
        return 0
    return cmd_push(args.host, args.webhook_id)


if __name__ == "__main__":
    sys.exit(main())
