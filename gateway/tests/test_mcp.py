"""MCP at /mcp (PLAN M12.1-12.3): bearer key per external agent, the same results as REST, every order to approval."""

import pytest
from app.identity import key_hash
from app.main import create_app
from conftest import FakeLLM, FakeVoice
from fastapi.testclient import TestClient

AGENT_KEY = "test-agent-key"
ACCEPT = {"Accept": "application/json, text/event-stream"}
AUTH = {**ACCEPT, "Authorization": f"Bearer {AGENT_KEY}"}
TOOLS = {
    "search_products",
    "get_product",
    "plan_quantity",
    "get_offers",
    "add_to_basket",
    "get_basket",
    "update_basket_line",
    "remove_basket_line",
    "quote_basket",
    "create_quote",
    "place_order",
    "get_order",
    "get_approval",
}
READ_ONLY = {"search_products", "get_product", "plan_quantity", "get_offers", "get_basket", "get_order", "get_approval"}
NEED = {
    "query": "laktoositon maito",
    "heads": ["maito", "maitojuoma"],
    "must_claims": ["FREE_FROM_LACTOSE"],
    "amount": 1000,
    "unit": "L",
    "need_date": "2026-11-16",
}


@pytest.fixture
def mcp(settings):
    settings.mcp_agent_keys = {"test-agent": key_hash(AGENT_KEY)}
    settings.mcp_allowed_hosts = ["testserver"]  # TestClient's Host header
    with TestClient(create_app(settings, voice=FakeVoice(), llm=FakeLLM())) as c:  # runs the MCP session manager
        yield c


def rpc(client, method: str, params: dict | None = None, headers: dict | None = None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=AUTH if headers is None else headers)


def call(client, name: str, **arguments) -> dict:
    r = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200
    result = r.json()["result"]
    assert not result.get("isError"), result
    return result["structuredContent"]


def test_tool_list_needs_a_known_key(mcp):
    r = rpc(mcp, "tools/list")
    assert r.status_code == 200
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    assert set(tools) == TOOLS  # not confirm, not approval decisions
    for name, t in tools.items():
        assert t["annotations"]["readOnlyHint"] is (name in READ_ONLY)
        assert {"status", "reason_code", "message_for_user", "warnings"} <= set(t["outputSchema"]["properties"])
        assert all(p.get("description") for p in t["inputSchema"]["properties"].values()), name
    assert tools["place_order"]["annotations"]["idempotentHint"] is True

    assert rpc(mcp, "tools/list", headers=ACCEPT).status_code == 401
    assert rpc(mcp, "tools/list", headers={**ACCEPT, "Authorization": "Bearer not-a-key"}).status_code == 401
    assert rpc(mcp, "tools/list", headers={**ACCEPT, "Authorization": AGENT_KEY}).status_code == 401  # no scheme


def test_get_mcp_is_405(mcp):
    assert mcp.get("/mcp", headers=AUTH).status_code == 405
    assert mcp.get("/mcp").status_code == 405


def test_host_and_origin_allowlists(mcp):
    assert rpc(mcp, "tools/list", headers={**AUTH, "Host": "evil.example"}).status_code == 421
    assert rpc(mcp, "tools/list", headers={**AUTH, "Origin": "https://evil.example"}).status_code == 403


def test_search_over_mcp_equals_rest(mcp):
    need = {"query": "laktoositon maito", "heads": ["maito"], "must_claims": ["FREE_FROM_LACTOSE"]}
    assert mcp.post("/api/login", json={"buyer_id": "chef"}).status_code == 200
    rest = mcp.post("/v1/products/search", json=need).json()
    assert call(mcp, "search_products", **need) == rest
    assert call(mcp, "get_product", product_id="464306") == mcp.get("/v1/products/464306").json()


def test_quote_and_order_over_mcp_end_in_requires_escalation(mcp):
    offers = call(mcp, "get_offers", **NEED, buyer_id="chef")  # an identity argument is ignored
    q = call(mcp, "create_quote", offer_id=offers["options"][0]["offer_id"])
    assert (q["status"], q["quote"]["buyer_id"]) == ("ready_for_complete", "external_agent")

    # The on-screen Confirm needs the buyer's web cookie: the agent's key does not reach it.
    assert mcp.post(f"/v1/quotes/{q['quote_id']}/confirm", headers=AUTH).status_code == 401

    o1 = call(mcp, "place_order", quote_id=q["quote_id"])  # its own call is its confirmation (M8.1)
    o2 = call(mcp, "place_order", quote_id=q["quote_id"])
    assert (o1["status"], o1["reason_code"]) == ("requires_escalation", "limit_exceeded")
    assert o1["order_id"] == o2["order_id"] and o1["approval_id"]
    assert call(mcp, "get_order", order_id=o1["order_id"])["status"] == "requires_escalation"
    assert call(mcp, "get_approval", approval_id=o1["approval_id"])["status"] == "requires_escalation"


def test_small_basket_order_still_needs_approval(mcp):
    """The external-agent mandate is quote only: even an order far below a chef's cap goes to a human."""
    b = call(mcp, "add_to_basket", **{**NEED, "amount": 10}, basket_id="new")
    assert b["basket"]["lines"]
    q = call(mcp, "quote_basket", basket_id=b["basket_id"])
    assert q["status"] == "ready_for_complete", q
    o = call(mcp, "place_order", quote_id=q["quote_id"])
    assert o["status"] == "requires_escalation"
    assert call(mcp, "get_basket", basket_id=b["basket_id"])["basket"]["status"] == "ordered"


def test_unknown_order_is_a_tool_error(mcp):
    r = rpc(mcp, "tools/call", {"name": "get_order", "arguments": {"order_id": "O-NOPE"}})
    assert r.status_code == 200 and r.json()["result"]["isError"] is True
