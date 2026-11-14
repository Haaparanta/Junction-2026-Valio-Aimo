from app.main import create_app

AGENT_TOOLS = {
    "search_products",
    "get_product",
    "plan_quantity",
    "get_offers",
    "find_substitutes",
    "create_quote",
    "place_order",
    "get_order",
    "get_approval",
    "cancel_order",
}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_openapi_lists_every_section5_tool(settings):
    spec = create_app(settings).openapi()
    ops = {
        op["operationId"]: op
        for path in spec["paths"].values()
        for op in path.values()
        if "agent-tools" in op.get("tags", [])
    }
    assert set(ops) == AGENT_TOOLS
    for name, op in ops.items():
        assert op["x-agent-tool"]["description"], name
        assert {"status", "message_for_user"} <= set(op["x-agent-tool"]["response_filter"])


def test_agent_request_schemas_are_flat_and_described(settings):
    """ElevenLabs tool schemas: no anyOf/Optional, a description on every request property."""
    spec = create_app(settings).openapi()
    schemas = spec["components"]["schemas"]
    for name in [
        "SearchRequest",
        "OffersRequest",
        "PlanQuantityRequest",
        "SubstitutesRequest",
        "CreateQuoteRequest",
        "PlaceOrderRequest",
        "CancelOrderRequest",
    ]:
        for prop, s in schemas[name]["properties"].items():
            assert "anyOf" not in s, (name, prop)
            assert s.get("description"), (name, prop)


def test_tools_need_a_caller(client):
    assert client.post("/v1/offers", json={}).status_code == 401
