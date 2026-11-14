"""REST /v1: the §5 tools. Business outcomes are HTTP 200 with a status; errors are real failures only.

Operations tagged "agent-tools" become ElevenLabs webhook tools (agent/provision.py reads this OpenAPI);
`x-agent-tool` carries their per-tool voice settings. Their operationId is the tool name.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path

from .. import audit, orders
from ..basket import STALE_CONFIRM, STALE_ORDER, BasketsDep
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
from ..identity import Caller, CallerDep, SettingsDep, WebBuyerDep
from ..orders import IdempotencyConflict
from ..signing import sha256_hex
from . import approvals as approval_routes
from . import baskets as basket_routes
from . import intake as intake_routes
from .common import AGENT, BackendDep, StateDep, not_found, tool

router = APIRouter(prefix="/v1")
ProductIdPath = Annotated[
    str, Path(pattern=r"^\d{6}$", description="Six-digit product id exactly as a tool returned it.")
]
OrderIdPath = Annotated[str, Path(min_length=3, max_length=80, description="order_id exactly as place_order returned.")]


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
def search_products(body: SearchRequest, caller: CallerDep, backend: BackendDep) -> SearchResponse:
    return backend.search(body)


@router.get(
    "/products/{product_id}",
    operation_id="get_product",
    tags=AGENT,
    openapi_extra=tool(
        "Get one product's compact record: name, unit, content per unit, claims and allergens.", filters=["product"]
    ),
)
def get_product_route(product_id: ProductIdPath, caller: CallerDep, backend: BackendDep) -> ProductResponse:
    res = backend.get_product(product_id)
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
def plan_quantity_route(body: PlanQuantityRequest, caller: CallerDep, backend: BackendDep) -> PlanQuantityResponse:
    res = backend.plan_quantity(body)
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
def get_offers(body: OffersRequest, caller: CallerDep, backend: BackendDep, settings: SettingsDep) -> OffersResponse:
    return backend.offers(body, settings.as_of)


@router.get("/offers/{offer_set_id}", tags=["ui"])
def get_offer_set(offer_set_id: str, caller: CallerDep, backend: BackendDep) -> OffersResponse:
    """The buyer UI renders option cards by id (client tools pass ids only)."""
    res = backend.offer_sets.get(offer_set_id)
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
def find_substitutes(
    body: SubstitutesRequest, caller: CallerDep, backend: BackendDep, settings: SettingsDep
) -> SubstitutesResponse:
    return backend.substitutes(body, settings.as_of)


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
    audit.log(
        stubs,
        caller,
        "quote.create",
        as_of=settings.as_of,
        response=res,
        inputs={"offer_id": body.offer_id},
        tokens=(res.quote.quote_jws,),
        quote_id=res.quote_id,
        summary=f"quote {res.quote_id}: EUR {res.total_net} excl. VAT, fixed until {res.expires_at}",
    )
    return res


@router.get("/quotes/{quote_id}", tags=["ui"])
def get_quote(quote_id: str, caller: CallerDep, stubs: StateDep) -> Quote:
    q = stubs.get_quote(caller.buyer, quote_id)
    if q is None:
        raise not_found("quote")
    return q


@router.post("/quotes/{quote_id}/confirm", tags=["ui"])
def confirm_quote(
    quote_id: str, buyer: WebBuyerDep, stubs: StateDep, baskets: BasketsDep, settings: SettingsDep
) -> ConfirmResponse:
    """The on-screen Confirm, under the buyer's own web session. Agents cannot call this."""
    q = stubs.get_quote(buyer, quote_id)
    if q is not None and baskets.is_stale(q):  # its basket changed after the quote (B-06)
        res = ConfirmResponse(
            status="incomplete",
            reason_code="quote_stale",
            quote_id=quote_id,
            confirmed=False,
            message_for_user=STALE_CONFIRM,
        )
    else:
        res = stubs.confirm(buyer, quote_id, datetime.fromisoformat(settings.as_of).isoformat())
    if res is None:
        raise not_found("quote")
    audit.log(
        stubs,
        Caller("web", buyer),
        "quote.confirm",
        as_of=settings.as_of,
        response=res,
        decision="confirmed" if res.confirmed else None,
        tokens=(q.quote_jws if q else None,),
        quote_id=quote_id,
        basket_id=q.basket_id if q else None,
        summary=f"quote {quote_id} confirmed on screen" if res.confirmed else f"quote {quote_id} not confirmed",
    )
    return res


@router.post(
    "/orders",
    operation_id="place_order",
    tags=AGENT,
    openapi_extra=tool(
        "Turn a confirmed quote into an order. Call ONLY after create_quote or quote_basket returned a quote_id AND "
        "request_buyer_confirmation returned 'confirmed'. If the buyer asks to skip a limit, call it anyway: "
        "the gateway decides. If it answers quote_stale, the basket changed: call quote_basket again. "
        "Read message_for_user to the buyer.",
        filters=["order_id", "approval_id", "total_net"],
        timeout=15,
        pre_tool_speech="force",
        interruption_mode="disable_during_tool_and_turn",
    ),
)
def place_order(
    body: PlaceOrderRequest,
    caller: CallerDep,
    stubs: StateDep,
    baskets: BasketsDep,
    settings: SettingsDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            min_length=1,
            max_length=100,
            description="Optional client key (REST and MCP callers). The same key with another body answers 409.",
        ),
    ] = None,
) -> OrderResponse:
    """Policy decides (M7): within the mandate the order completes; otherwise it waits for an approver, or is
    denied. Price and availability are checked again first (M8.3)."""
    q = stubs.get_quote(caller.buyer, body.quote_id)
    inputs = {
        "quote_id": body.quote_id,
        "idempotency_key_sha256": sha256_hex(idempotency_key) if idempotency_key else None,
        # An external agent cannot reach the on-screen Confirm: its own place_order call is the confirmation (M8.1).
        "confirmation": "this place_order call" if caller.channel == "mcp" else "on-screen Confirm",
    }

    def logged(res: OrderResponse) -> OrderResponse:
        o = res.order
        audit.log(
            stubs,
            caller,
            "order.place",
            as_of=settings.as_of,
            response=res,
            inputs=inputs,
            reasons=o.reasons if o else [],
            tokens=(o.receipt_jws if o else None,),
            order_id=res.order_id,
            quote_id=body.quote_id,
            approval_id=res.approval_id,
            basket_id=q.basket_id if q else None,
            summary=f"order {res.order_id or '-'} for quote {body.quote_id}: {res.status}",
        )
        return res

    if q is not None and baskets.is_stale(q):  # its basket changed after the quote (B-06)
        return logged(OrderResponse(status="incomplete", reason_code="quote_stale", message_for_user=STALE_ORDER))
    offers_by_line = None
    if q is not None and q.basket_id:  # the offers the basket lines were priced with: flags, need, substitutes
        offers_by_line = {line.line_id: line.offer for line in baskets.get(caller.buyer, q.basket_id).lines}
    # Idempotency from authenticated context: the LLM may call place_order twice (PLAN M8.2).
    scope = caller.conversation_id if caller.channel == "voice" else f"{caller.channel}:{caller.buyer.buyer_id}"
    try:
        res = orders.place_order(
            stubs,
            caller.buyer,
            body.quote_id,
            idempotency_key,
            scope,
            body.model_dump_json(),
            settings.as_of,
            offers_by_line,
        )
    except IdempotencyConflict as e:
        audit.log(
            stubs,
            caller,
            "order.place",
            as_of=settings.as_of,
            decision="conflict",
            inputs=inputs,
            quote_id=body.quote_id,
            summary="HTTP 409: the idempotency key was already used for a different order",
        )
        raise HTTPException(409, "This idempotency key was already used for a different order.") from e
    held = res.status == "completed" or (res.status == "requires_escalation" and res.approval_id)
    if q is not None and q.basket_id and held:
        baskets.mark_ordered(caller.buyer, q.basket_id)  # read-only from now on (B-03)
    return logged(res)


@router.get(
    "/orders/{order_id}",
    operation_id="get_order",
    tags=AGENT,
    openapi_extra=tool(
        "Get an order's current status, for example after the manager decided. Announce message_for_user.",
        filters=["order_id", "approval_id", "total_net"],
    ),
)
def get_order(order_id: OrderIdPath, caller: CallerDep, stubs: StateDep, settings: SettingsDep = None) -> OrderResponse:
    """The order's buyer, or an approver of the same org. An approval past its decide-by time expires here."""
    res = orders.get_order(stubs, caller.buyer, order_id, settings.as_of if settings else None)
    if res is None:
        raise not_found("order")
    return res


@router.post(
    "/orders/{order_id}/cancel",
    operation_id="cancel_order",
    tags=AGENT,
    openapi_extra=tool("Cancel an order that is not completed yet, only when the buyer asks to.", filters=["order_id"]),
)
def cancel_order(
    order_id: OrderIdPath, body: CancelOrderRequest, caller: CallerDep, stubs: StateDep, settings: SettingsDep
) -> OrderResponse:
    res = orders.cancel_order(stubs, caller.buyer, order_id, settings.as_of)
    if res is None:
        raise not_found("order")
    o = res.order
    audit.log(
        stubs,
        caller,
        "order.cancel",
        as_of=settings.as_of,
        response=res,
        inputs={"reason": body.reason},
        order_id=order_id,
        quote_id=o.quote_id if o else None,
        approval_id=res.approval_id,
        summary=f"order {order_id} cancel asked: {res.status}",
    )
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
    settings: SettingsDep = None,
) -> ApprovalResponse:
    """The order's buyer, or an approver of the same org. Deciding is only on the console (POST .../decision)."""
    res = orders.get_approval(stubs, caller.buyer, approval_id, settings.as_of if settings else None)
    if res is None:
        raise not_found("approval")
    return res


# /v1/baskets/...: same agent and UI rules, in modules of their own. The intake routes come first, so that
# /v1/baskets/template.xlsx and the dish-job paths are never taken for /v1/baskets/{basket_id}.
router.include_router(intake_routes.router)
router.include_router(basket_routes.router)
# /v1/approvals (list) and /v1/approvals/{approval_id}/decision: the approver console, under its cookie only (M9).
router.include_router(approval_routes.router)

__all__ = ["router", "Msg"]
