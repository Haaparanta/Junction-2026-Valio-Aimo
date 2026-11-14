"""MCP at /mcp (PLAN M12.1-12.3): a thin adapter over the same service functions as REST /v1.

* SDK 2.x `MCPServer`, streamable HTTP in stateless JSON mode: one POST per JSON-RPC message, no sessions,
  no server-sent events. `GET /mcp` answers 405.
* Every request needs `Authorization: Bearer <key>` with a key from MCP_AGENT_KEYS (stored as SHA-256). No key or
  an unknown key gives 401. The caller is always the external-agent mandate (identity.bearer_caller), never an
  argument. Host and Origin are checked against the allowlists in settings plus PUBLIC_HOST.
* Each tool calls the REST route function with the authenticated caller, so REST and MCP give the same results.
  Arguments and output schemas come from the contract's pydantic models; annotations say read-only or write.
* An external agent cannot press the on-screen Confirm (that route needs the buyer's web cookie). Its own
  `place_order` call under its key is its confirmation (M8.1); its mandate then sends the order to a human approver.
"""

import copy
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .api import baskets as basket_routes
from .api import tools as rest
from .basket import service as basket_service
from .contract import (
    BASKET_ID_FIELD,
    ID_FIELD,
    AddToBasketRequest,
    ApprovalResponse,
    BasketLineRequest,
    BasketQuoteResponse,
    BasketRequest,
    BasketResponse,
    CreateQuoteRequest,
    OffersRequest,
    OffersResponse,
    OrderResponse,
    PlaceOrderRequest,
    PlanQuantityRequest,
    PlanQuantityResponse,
    ProductId,
    ProductResponse,
    QuoteResponse,
    SearchRequest,
    SearchResponse,
    UpdateBasketLineRequest,
)
from .identity import Caller, bearer_caller
from .settings import Settings

PATH = "/mcp"
CALLER = "mcp_caller"  # key in the ASGI scope state, set by AgentKeyGate after the key check

INSTRUCTIONS = """Valio Aimo agent gateway for AI purchasing agents. The gateway decides; you plan and explain.
Every result has status, reason_code, message_for_user (fi, en) and warnings. Money is a decimal string in EUR.
Flow: search_products or get_offers, then create_quote (one offer) or add_to_basket and quote_basket, then
place_order with the quote_id. Your place_order call is your confirmation; under your mandate every order goes
to a human approver (status requires_escalation), so poll get_order or get_approval. Never invent ids or prices."""


# ---- argument models for the tools whose REST form takes the id in the path ----


class ProductIdArgs(BaseModel):
    product_id: ProductId = ID_FIELD


class OrderIdArgs(BaseModel):
    order_id: str = Field(min_length=3, max_length=80, description="order_id exactly as place_order returned.")


class ApprovalIdArgs(BaseModel):
    approval_id: str = Field(min_length=3, max_length=80, description="approval_id exactly as a tool returned it.")


class BasketIdArgs(BaseModel):
    basket_id: str = BASKET_ID_FIELD


READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
WRITE_IDEMPOTENT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
REMOVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)


def _signature(args: type[BaseModel], result: type[BaseModel]) -> inspect.Signature:
    """The tool's MCP signature: one keyword argument per field of the flat request model, each with its
    description, default and constraints, so the input schema equals the REST request schema."""
    params = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Annotated[f.annotation, copy.copy(f)])
        for name, f in args.model_fields.items()
    ]
    return inspect.Signature(params, return_annotation=result)


class Tools:
    """The tools of one app. Each one runs the REST route function with the caller from the bearer key."""

    def __init__(self, app: FastAPI, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    @property
    def stubs(self) -> Any:
        return self.app.state.stubs

    @property
    def backend(self) -> Any:
        return self.app.state.backend

    @property
    def baskets(self) -> Any:
        return basket_service(self.app, self.settings)

    def register(self, server: MCPServer) -> None:
        s = self
        defs: list[tuple[str, type[BaseModel], type[BaseModel], ToolAnnotations, str, Callable[..., Any]]] = [
            (
                "search_products",
                SearchRequest,
                SearchResponse,
                READ,
                "Find catalogue products for a need. Fill heads with the product type in Finnish base form and "
                "exclude with words to drop; put diet needs in must_claims and must_not_allergens. The gateway "
                "applies the diet filters.",
                lambda c, a: rest.search_products(a, c, s.backend),
            ),
            (
                "get_product",
                ProductIdArgs,
                ProductResponse,
                READ,
                "Get one product's compact record: name, unit, content per unit, claims and allergens, plus "
                "schema.org JSON-LD.",
                lambda c, a: rest.get_product_route(a.product_id, c, s.backend),
            ),
            (
                "plan_quantity",
                PlanQuantityRequest,
                PlanQuantityResponse,
                READ,
                "Turn a need in litres, kilograms or pieces into order units for one product, with lot-size "
                "rounding and overshoot. Never do this arithmetic yourself.",
                lambda c, a: rest.plan_quantity_route(a, c, s.backend),
            ),
            (
                "get_offers",
                OffersRequest,
                OffersResponse,
                READ,
                "Get feasible, ranked good-better-best options for a need (what, how much, by when), with flags "
                "and explanations. Never state a price that is not in this result.",
                lambda c, a: rest.get_offers(a, c, s.backend, s.settings),
            ),
            (
                "add_to_basket",
                AddToBasketRequest,
                BasketResponse,
                WRITE,
                "Add one need (what, how much, by when) to a basket. The gateway prices it, picks the best offer "
                "and keeps the alternatives. Use basket_id 'new' only for the first item, then always the "
                "basket_id this tool returned.",
                lambda c, a: basket_routes.add_to_basket(a, c, s.baskets),
            ),
            (
                "get_basket",
                BasketIdArgs,
                BasketResponse,
                READ,
                "Get a basket: its lines with status, chosen offer and alternatives, and the gateway totals.",
                lambda c, a: basket_routes.get_basket(a.basket_id, c, s.baskets),
            ),
            (
                "update_basket_line",
                UpdateBasketLineRequest,
                BasketResponse,
                WRITE_IDEMPOTENT,
                "Change one basket line: the amount, the unit, the delivery date, or offer_id to choose one of "
                "the line's alternatives. 0 and empty strings keep a value. The gateway prices the line again.",
                lambda c, a: basket_routes.update_basket_line(a, c, s.baskets),
            ),
            (
                "remove_basket_line",
                BasketLineRequest,
                BasketResponse,
                REMOVE,
                "Remove one basket line. The buyer can restore it on screen.",
                lambda c, a: basket_routes.remove_basket_line(a, c, s.baskets),
            ),
            (
                "quote_basket",
                BasketRequest,
                BasketQuoteResponse,
                WRITE,
                "Make one fixed-price, signed quote for every line of the basket. If it answers "
                "basket_incomplete, resolve the lines in open_lines first, then call it again.",
                lambda c, a: basket_routes.quote_basket(a, c, s.baskets),
            ),
            (
                "create_quote",
                CreateQuoteRequest,
                QuoteResponse,
                WRITE,
                "Create a fixed-price, signed quote with an expiry from one offer_id that get_offers returned.",
                lambda c, a: rest.create_quote(a, c, s.stubs, s.settings),
            ),
            (
                "place_order",
                PlaceOrderRequest,
                OrderResponse,
                WRITE_IDEMPOTENT,
                "Turn a quote into an order. This call is your confirmation of the quote. The gateway applies "
                "your mandate: an order that needs a human answers requires_escalation with an approval_id. "
                "Calling it again for the same quote returns the same order.",
                lambda c, a: s.place_order(c, a),
            ),
            (
                "get_order",
                OrderIdArgs,
                OrderResponse,
                READ,
                "Get an order's current status, for example after the approver decided.",
                lambda c, a: rest.get_order(a.order_id, c, s.stubs),
            ),
            (
                "get_approval",
                ApprovalIdArgs,
                ApprovalResponse,
                READ,
                "Get the status of an approval request. Only a human approver on their own console decides it.",
                lambda c, a: rest.get_approval(a.approval_id, c, s.stubs),
            ),
        ]
        for name, args, result, annotations, description, run in defs:
            server.add_tool(
                self._tool(name, args, result, run), name=name, description=description, annotations=annotations
            )

    def _tool(
        self, name: str, args: type[BaseModel], result: type[BaseModel], run: Callable[[Caller, Any], Any]
    ) -> Callable[..., Any]:
        def fn(ctx: Context, **kwargs: Any) -> Any:
            caller = _caller(ctx)
            try:
                return run(caller, args.model_validate(kwargs))
            except HTTPException as e:  # a real failure on REST (404 not found or not yours): a tool error here
                raise ToolError(str(e.detail)) from e

        ctx = inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)
        sig = _signature(args, result)
        fn.__signature__ = sig.replace(parameters=[*sig.parameters.values(), ctx])  # type: ignore[attr-defined]
        fn.__name__ = name
        return fn

    def place_order(self, caller: Caller, body: PlaceOrderRequest) -> OrderResponse:
        """M8.1: for an external agent, its own place_order under its key is the buyer's confirmation (it cannot
        reach the on-screen Confirm). A stale basket quote is left unconfirmed, so REST answers quote_stale."""
        q = self.stubs.get_quote(caller.buyer, body.quote_id)
        if q is not None and not q.confirmed and not self.baskets.is_stale(q):
            self.stubs.confirm(caller.buyer, body.quote_id, datetime.fromisoformat(self.settings.as_of).isoformat())
        return rest.place_order(body, caller, self.stubs, self.baskets, self.settings)


def _caller(ctx: Context) -> Caller:
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    caller = getattr(getattr(request, "state", None), CALLER, None) if request is not None else None
    if not isinstance(caller, Caller):  # AgentKeyGate always sets it; never fall back to an argument
        raise ToolError("Unknown caller.")
    return caller


class AgentKeyGate:
    """ASGI gate in front of the MCP transport: 405 for GET, 401 without a known bearer key."""

    def __init__(self, inner: ASGIApp, settings: Settings) -> None:
        self.inner = inner
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if request.method != "POST":  # stateless JSON mode: no SSE stream, no session to delete
            await JSONResponse({"detail": "Use POST."}, 405, headers={"Allow": "POST"})(scope, receive, send)
            return
        caller = bearer_caller(self.settings, request.headers.get("authorization"))
        if caller is None:
            res = JSONResponse({"detail": "Unknown caller."}, 401, headers={"WWW-Authenticate": "Bearer"})
            await res(scope, receive, send)
            return
        scope.setdefault("state", {})[CALLER] = caller
        await self.inner(scope, receive, send)


def security(settings: Settings) -> TransportSecuritySettings:
    hosts, origins = list(settings.mcp_allowed_hosts), list(settings.mcp_allowed_origins)
    if settings.public_host:
        hosts += [settings.public_host, f"{settings.public_host}:*"]
        origins += [f"https://{settings.public_host}"]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


def build(app: FastAPI, settings: Settings) -> MCPServer:
    server = MCPServer("valio-aimo-gateway", title="Valio Aimo agent gateway", instructions=INSTRUCTIONS)
    Tools(app, settings).register(server)
    return server


def mount(app: FastAPI, settings: Settings) -> MCPServer:
    """Serve MCP at /mcp on this app and run its session manager in the app's lifespan."""
    server = build(app, settings)
    server.streamable_http_app(
        streamable_http_path=PATH, json_response=True, stateless_http=True, transport_security=security(settings)
    )
    manager = server.session_manager
    app.router.routes.append(Route(PATH, AgentKeyGate(StreamableHTTPASGIApp(manager), settings)))
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: Any) -> AsyncIterator[Any]:
        async with manager.run(), previous(a) as state:
            yield state

    app.router.lifespan_context = lifespan
    app.state.mcp = server
    return server
