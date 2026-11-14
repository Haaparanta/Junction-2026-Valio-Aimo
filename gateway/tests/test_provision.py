"""agent/provision.py turns the gateway OpenAPI into ElevenLabs webhook tools."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("provision", ROOT / "agent" / "provision.py")
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


def tools() -> dict:
    return {t["name"]: t for t in provision.webhook_tools(provision.gateway_openapi())}


def test_every_tool_sends_the_three_identity_headers():
    for name, t in tools().items():
        h = t["api_schema"]["request_headers"]
        assert h["X-Conversation-Id"] == {"variable_name": "system__conversation_id"}, name
        assert h["X-Session-Token"] == {"variable_name": "secret__session_token"}, name
        assert "secret_id" in h["X-Gateway-Key"], name
        assert t["api_schema"]["url"].startswith("https://{{system__env_gateway_host}}/v1/"), name
        assert t["tool_error_handling_mode"] == "passthrough", name


def test_llm_never_fills_identity():
    for name, t in tools().items():
        body = t["api_schema"].get("request_body_schema", {}).get("properties", {})
        assert not {"buyer", "buyer_id", "conversation_id", "session_token"} & set(body), name


def test_place_order_is_not_interruptible_and_filtered():
    po = tools()["place_order"]
    assert po["interruption_mode"] == "disable_during_tool_and_turn"
    assert po["api_schema"]["response_filter"]["mode"] == "allow"
    assert po["api_schema"]["request_body_schema"]["required"] == ["quote_id"]


def test_schemas_have_no_refs_or_anyof():
    text = json.dumps(list(tools().values()))
    assert "$ref" not in text and "anyOf" not in text


def test_committed_tool_configs_are_current():
    assert provision.cmd_tools(check=True) == 0


def test_agent_build_has_client_tools_and_no_secret():
    agent = provision.build_agent()
    names = {t["name"] for t in agent["conversation_config"]["agent"]["prompt"]["tools"]}
    assert {"show_products", "show_quote", "show_approval_request", "request_buyer_confirmation"} <= names
    confirm = next(
        t for t in agent["conversation_config"]["agent"]["prompt"]["tools"] if t["name"] == "request_buyer_confirmation"
    )
    assert confirm["expects_response"] is True and confirm["response_timeout_secs"] == 120
    assert agent["platform_settings"]["auth"]["enable_auth"] is True
    assert agent["platform_settings"]["privacy"]["retention_days"] <= 30
    assert agent["conversation_config"]["agent"]["prompt"]["temperature"] == 0
