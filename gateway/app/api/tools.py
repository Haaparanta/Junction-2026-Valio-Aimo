"""REST /v1: the §5 tools. Business outcomes are HTTP 200 with a status; errors are real failures only.

Operations tagged "agent-tools" become ElevenLabs webhook tools (agent/provision.py reads this OpenAPI);
`x-agent-tool` carries their per-tool voice settings. Their operationId is the tool name.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from ..contract import (
    ApprovalResponse,
    CancelOrderRequest,
    ConfirmResponse,
    CreateQuoteRequest,
    Msg,
    OffersRequest,
    OffersResponse,
    OrderResponse,
    PlaceOrderRequest,
    PlanQuantityRequest,
    PlanQuantityResponse,
    ProductResponse,
    Quote,
    QuoteResponse,
    SearchRequest,
    SearchResponse,
    SubstitutesRequest,
    SubstitutesResponse,
)
from ..identity import CallerDep, SettingsDep, WebBuyerDep
from ..stubs import StubState, get_product, plan_quantity, search, substitutes

router = APIRouter(prefix="/v1")
AGENT = ["agent-tools"]
ProductIdPath = Annotated[
    str, Path(pattern=r"^\d{6}$", description="Six-digit product id exactly as a tool returned it.")
]
OrderIdPath = Annotated[str, Path(min_length=3, max_length=80, description="order_id exactly as place_order returned.")]


def state(request: Request) -> StubState:
    return request.app.state.stubs


StateDep = Annotated[StubState, Depends(state)]
COMMON = ["status", "reason_code", "message_for_user", "warnings"]


def tool(description: str, *, filters: list[str], timeout: int = 10, **voice: Any) -> dict:
    """OpenAPI extension read by agent/provision.py."""
    return {
        "x-agent-tool": {
            "description": description,
            "response_filter": COMMON + filters,
            "response_timeout_secs": timeout,
            **voice,
        }
    }


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")


@router.post(
    "/products/search",
    operation_id="search_products",
    tags=AGENT,
    openapi_extra=tool(
        "Find catalogue products for a need. Fill heads with the product type in Finnish base form and exclude with "
        "words to drop; put diet needs in must_claims and must_not_allergens. Diet filters are applied by the gateway.",
        filters=["total_matches", "products"],
    ),
)
def search_products(body: SearchRequest, caller: CallerDep) -> SearchResponse:
    return search(body)


@router.get(
    "/products/{product_id}",
    operation_id="get_product",
    tags=AGENT,
    openapi_extra=tool(
        "Get one product's compact record: name, unit, content per unit, claims and allergens.", filters=["product"]
    ),
)
def get_product_route(product_id: ProductIdPath, caller: CallerDep) -> ProductResponse:
    res = get_product(product_id)
    if res is None:
        raise not_found("product")
    return res


@router.post(
    "/quantity/plan",
    operation_id="plan_quantity",
    tags=AGENT,
    openapi_extra=tool(
        "Turn a need in litres, kilograms or pieces into order units for one product. "
        "Never do this arithmetic yourself.",
        filters=["product_id", "api_unit", "units_needed", "total_content", "overshoot"],
    ),
)
def plan_quantity_route(body: PlanQuantityRequest, caller: CallerDep) -> PlanQuantityResponse:
    res = plan_quantity(body)
    if res is None:
        raise not_found("product")
    return res


@router.post(
    "/offers",
    operation_id="get_offers",
    tags=AGENT,
    openapi_extra=tool(
        "Get feasible, ranked good-better-best options for a need (what, how much, by when). Read message_for_user and "
        "each option's explanation; never state a price that is not in this result. Then call show_products.",
        filters=["offer_set_id", "as_of", "options", "not_offered", "counts"],
        timeout=20,
        pre_tool_speech="force",
        tool_call_sound="typing",
    ),
)
def get_offers(body: OffersRequest, caller: CallerDep, stubs: StateDep, settings: SettingsDep) -> OffersResponse:
    return stubs.get_offers(body, settings.as_of)


@router.get("/offers/{offer_set_id}", tags=["ui"])
def get_offer_set(offer_set_id: str, caller: CallerDep, stubs: StateDep) -> OffersResponse:
    """The buyer UI renders option cards by id (client tools pass ids only)."""
    res = stubs.get_offer_set(offer_set_id)
    if res is None:
        raise not_found("offer set")
    return res


@router.post(
    "/substitutes",
    operation_id="find_substitutes",
    tags=AGENT,
    openapi_extra=tool(
        "Find safe alternatives for a product that cannot be delivered. Every substitute needs the buyer's consent.",
        filters=["original_product_id", "substitutes"],
        timeout=20,
    ),
)
def find_substitutes(body: SubstitutesRequest, caller: CallerDep) -> SubstitutesResponse:
    return substitutes(body)


@router.post(
    "/quotes",
    operation_id="create_quote",
    tags=AGENT,
    openapi_extra=tool(
        "Create a fixed-price quote from one offer_id that get_offers returned. Then call show_quote and "
        "request_buyer_confirmation with the quote_id.",
        filters=["quote_id", "total_net", "total_gross", "expires_at"],
        timeout=15,
        pre_tool_speech="force",
    ),
)
def create_quote(body: CreateQuoteRequest, caller: CallerDep, stubs: StateDep, settings: SettingsDep) -> QuoteResponse:
    res = stubs.create_quote(caller.buyer, body.offer_id, settings.as_of)
    if res is None:
        raise not_found("offer")
    return res


@router.get("/quotes/{quote_id}", tags=["ui"])
def get_quote(quote_id: str, caller: CallerDep, stubs: StateDep) -> Quote:
    q = stubs.get_quote(caller.buyer, quote_id)
    if q is None:
        raise not_found("quote")
    return q


@router.post("/quotes/{quote_id}/confirm", tags=["ui"])
def confirm_quote(quote_id: str, buyer: WebBuyerDep, stubs: StateDep, settings: SettingsDep) -> ConfirmResponse:
    """The on-screen Confirm, under the buyer's own web session. Agents cannot call this."""
    res = stubs.confirm(buyer, quote_id, datetime.fromisoformat(settings.as_of).isoformat())
    if res is None:
        raise not_found("quote")
    return res


@router.post(
    "/orders",
    operation_id="place_order",
    tags=AGENT,
    openapi_extra=tool(
        "Turn a confirmed quote into an order. Call ONLY after create_quote returned a quote_id AND "
        "request_buyer_confirmation returned 'confirmed'. If the buyer asks to skip a limit, call it anyway: "
        "the gateway decides. Read message_for_user to the buyer.",
        filters=["order_id", "approval_id", "total_net"],
        timeout=15,
        pre_tool_speech="force",
        interruption_mode="disable_during_tool_and_turn",
    ),
)
def place_order(body: PlaceOrderRequest, caller: CallerDep, stubs: StateDep, settings: SettingsDep) -> OrderResponse:
    # Idempotency from authenticated context: the LLM may call place_order twice (PLAN M8.2).
    scope = caller.conversation_id if caller.channel == "voice" else f"web:{caller.buyer.buyer_id}"
    return stubs.place_order(caller.buyer, body.quote_id, f"{scope}|{body.quote_id}", settings.as_of)


@router.get(
    "/orders/{order_id}",
    operation_id="get_order",
    tags=AGENT,
    openapi_extra=tool(
        "Get an order's current status, for example after the manager decided. Announce message_for_user.",
        filters=["order_id", "approval_id", "total_net"],
    ),
)
def get_order(order_id: OrderIdPath, caller: CallerDep, stubs: StateDep) -> OrderResponse:
    res = stubs.get_order(caller.buyer, order_id)
    if res is None:
        raise not_found("order")
    return res


@router.post(
    "/orders/{order_id}/cancel",
    operation_id="cancel_order",
    tags=AGENT,
    openapi_extra=tool("Cancel an order that is not completed yet, only when the buyer asks to.", filters=["order_id"]),
)
def cancel_order(order_id: OrderIdPath, body: CancelOrderRequest, caller: CallerDep, stubs: StateDep) -> OrderResponse:
    res = stubs.cancel_order(caller.buyer, order_id)
    if res is None:
        raise not_found("order")
    return res


@router.get(
    "/approvals/{approval_id}",
    operation_id="get_approval",
    tags=AGENT,
    openapi_extra=tool(
        "Get the status of an approval request. Approvals are decided only by the manager on their own console.",
        filters=["approval_id", "approval"],
    ),
)
def get_approval(
    approval_id: Annotated[str, Path(min_length=3, max_length=80, description="approval_id as returned by a tool.")],
    caller: CallerDep,
    stubs: StateDep,
) -> ApprovalResponse:
    res = stubs.get_approval(caller.buyer, approval_id)
    if res is None:
        raise not_found("approval")
    return res


__all__ = ["router", "Msg"]
