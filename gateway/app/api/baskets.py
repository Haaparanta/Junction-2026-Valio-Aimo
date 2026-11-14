"""/v1/baskets (docs/basket-plan.md M22.3): agent tools under CallerDep, UI routes under the buyer cookie.

Agent tools and UI routes call the same service functions (app/basket.py). Business outcomes are HTTP 200 with a
status and a reason_code; 401 means not signed in, 404 not found or not yours, 422 invalid input. Identity comes
only from CallerDep or WebBuyerDep, never from arguments.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from .. import audit
from ..basket import Added, BasketsDep, Changed, LineDraft, respond, warnings_for
from ..contract import (
    AddToBasketRequest,
    BasketLine,
    BasketLinePatch,
    BasketLineRequest,
    BasketQuoteResponse,
    BasketRequest,
    BasketResponse,
    FromOfferRequest,
    UpdateBasketLineRequest,
)
from ..identity import Caller, CallerDep, WebBuyerDep
from .common import AGENT, StateDep, not_found, tool

router = APIRouter(prefix="/baskets")
BASKET_ID = r"^B-[0-9A-F]{10}$"
BasketIdPath = Annotated[
    str, Path(pattern=BASKET_ID, description="basket_id exactly as a basket tool returned it. Never invent or edit it.")
]
BasketIdOrNewPath = Annotated[
    str, Path(pattern=r"^(B-[0-9A-F]{10}|new)$", description="basket_id as returned, or 'new' to start a basket.")
]
LineIdPath = Annotated[int, Path(ge=1, le=10_000, description="line_id exactly as a basket tool returned it.")]
BASKET = ["basket_id", "basket", "line"]
VOICE_ALTERNATIVES = 3  # a voice tool result keeps each line's best 3 alternatives; the screen shows them all


def for_caller(res: BasketResponse, caller: Caller) -> BasketResponse:
    """The answer as this caller gets it: complete for the web, and for voice each line's alternatives cut to the
    best VOICE_ALTERNATIVES (in order), since every alternative carries a bilingual explanation and the agent
    reads the whole result. A warning says how many more are on screen."""
    if caller.channel != "voice":
        return res
    cut: dict[int, int] = {}

    def compact(line: BasketLine) -> BasketLine:
        extra = len(line.alternatives) - VOICE_ALTERNATIVES
        if extra <= 0:
            return line
        cut[line.line_id] = extra
        return line.model_copy(update={"alternatives": line.alternatives[:VOICE_ALTERNATIVES]})

    basket = res.basket.model_copy(update={"lines": [compact(x) for x in res.basket.lines]})
    line = compact(res.line) if res.line is not None else None
    if not cut:
        return res
    more = sum(cut.values())
    note = f"voice: {more} more alternative{'' if more == 1 else 's'} on screen"
    return res.model_copy(update={"basket": basket, "line": line, "warnings": [*warnings_for(basket, line), note]})


def added(a: Added) -> BasketResponse:
    if a.locked or not a.lines:
        return respond(a.basket, None, "locked")
    line = a.lines[0]
    return respond(a.basket, line, "duplicate" if line.line_id in a.existing else "added")


def changed(c: Changed) -> BasketResponse:
    return respond(c.basket, c.line, c.outcome)


# ---- agent tools (operationId = tool name); the buyer UI may call them with its cookie too ----


@router.post(
    "/lines",
    operation_id="add_to_basket",
    tags=AGENT,
    openapi_extra=tool(
        "Add one need (what, how much, by when) to a basket. The gateway prices it, picks the best offer and keeps "
        "the alternatives. Use basket_id 'new' only for the first item, then always the basket_id this tool "
        "returned. Fill heads, exclude, must_claims and must_not_allergens as for get_offers. Read message_for_user "
        "and never state a number that is not in this result. Then call show_basket with the basket_id.",
        filters=BASKET,
        timeout=20,
        pre_tool_speech="force",
        tool_call_sound="typing",
    ),
)
def add_to_basket(body: AddToBasketRequest, caller: CallerDep, baskets: BasketsDep) -> BasketResponse:
    draft = LineDraft.from_offers_request(body, "voice" if caller.channel == "voice" else "ui")
    res = added(baskets.add_lines(caller.buyer, body.basket_id, [draft], caller.conversation_id, dedupe=True))
    return for_caller(res, caller)


@router.get("/current", tags=["ui"])
def current_basket(buyer: WebBuyerDep, baskets: BasketsDep) -> BasketResponse:
    """The buyer's newest open basket, so a reload finds it again; 404 when there is none."""
    basket = baskets.current(buyer)
    if basket is None:
        raise not_found("open basket")
    return respond(basket)


@router.get(
    "/{basket_id}",
    operation_id="get_basket",
    tags=AGENT,
    openapi_extra=tool(
        "Get a basket: its lines with their status, chosen offer and alternatives, and the gateway totals. Read "
        "message_for_user; lines that need a choice or an amount are named there. Never state a number that is not "
        "in this result.",
        filters=["basket_id", "basket"],
    ),
)
def get_basket(basket_id: BasketIdPath, caller: CallerDep, baskets: BasketsDep) -> BasketResponse:
    return for_caller(respond(baskets.get(caller.buyer, basket_id)), caller)


@router.post(
    "/lines/update",
    operation_id="update_basket_line",
    tags=AGENT,
    openapi_extra=tool(
        "Change one basket line: the amount, the unit, the delivery date, or offer_id to choose one of the line's "
        "alternatives. 0 and empty strings keep a value. The gateway prices the line again: read message_for_user "
        "and never state a number that is not in this result. Then call show_basket.",
        filters=BASKET,
        timeout=15,
    ),
)
def update_basket_line(body: UpdateBasketLineRequest, caller: CallerDep, baskets: BasketsDep) -> BasketResponse:
    patch = BasketLinePatch(amount=body.amount, unit=body.unit, need_date=body.need_date, offer_id=body.offer_id)
    return for_caller(changed(baskets.update_line(caller.buyer, body.basket_id, body.line_id, patch)), caller)


@router.post(
    "/lines/remove",
    operation_id="remove_basket_line",
    tags=AGENT,
    openapi_extra=tool(
        "Remove one basket line, only when the buyer asks. The buyer can undo it on screen. Read message_for_user "
        "and never state a number that is not in this result. Then call show_basket.",
        filters=BASKET,
    ),
)
def remove_basket_line(body: BasketLineRequest, caller: CallerDep, baskets: BasketsDep) -> BasketResponse:
    return for_caller(changed(baskets.remove_line(caller.buyer, body.basket_id, body.line_id)), caller)


@router.post(
    "/quote",
    operation_id="quote_basket",
    tags=AGENT,
    openapi_extra=tool(
        "Make one fixed-price quote for every line of the basket. If it answers basket_incomplete, resolve the lines "
        "in open_lines first (choose an alternative, give an amount or remove the line), then call it again. Then call "
        "show_quote and request_buyer_confirmation with the quote_id. Never state a number that is not in this result.",
        filters=["basket_id", "quote_id", "total_net", "total_gross", "expires_at", "open_lines"],
        timeout=15,
        pre_tool_speech="force",
    ),
)
def quote_basket(body: BasketRequest, caller: CallerDep, baskets: BasketsDep) -> BasketQuoteResponse:
    res = baskets.quote(caller.buyer, body.basket_id)
    audit.log(
        baskets.stubs,
        caller,
        "basket.quote",
        as_of=baskets.settings.as_of,
        response=res,
        inputs={"basket_id": body.basket_id},
        tokens=(res.quote.quote_jws if res.quote else None,),
        quote_id=res.quote_id,
        basket_id=res.basket_id,
        summary=f"basket {res.basket_id} quote {res.quote_id or '-'}: {res.status}"
        + (f", EUR {res.total_net} excl. VAT" if res.total_net else ""),
    )
    return res


# ---- buyer UI: the web cookie only (voice headers alone get 401) ----


@router.patch("/{basket_id}/lines/{line_id}", tags=["ui"])
def patch_line(
    basket_id: BasketIdPath, line_id: LineIdPath, body: BasketLinePatch, buyer: WebBuyerDep, baskets: BasketsDep
) -> BasketResponse:
    """A click changed the amount, unit, date or chosen offer; the gateway prices the line again."""
    return changed(baskets.update_line(buyer, basket_id, line_id, body))


@router.delete("/{basket_id}/lines/{line_id}", tags=["ui"])
def delete_line(
    basket_id: BasketIdPath, line_id: LineIdPath, buyer: WebBuyerDep, baskets: BasketsDep
) -> BasketResponse:
    """Remove a line (a soft delete: the toast's Undo restores it)."""
    return changed(baskets.remove_line(buyer, basket_id, line_id))


@router.post("/{basket_id}/lines/{line_id}/restore", tags=["ui"])
def restore_line(
    basket_id: BasketIdPath, line_id: LineIdPath, buyer: WebBuyerDep, baskets: BasketsDep
) -> BasketResponse:
    """Undo a removal; the line comes back priced again."""
    return changed(baskets.restore_line(buyer, basket_id, line_id))


@router.post("/{basket_id}/lines/from-offer", tags=["ui"])
def add_from_offer(
    basket_id: BasketIdOrNewPath, body: FromOfferRequest, buyer: WebBuyerDep, baskets: BasketsDep, stubs: StateDep
) -> BasketResponse:
    """Add to basket from an option card (its need is the offer set's request, the product pinned), or with
    replace_line_id, put the card's product on that line instead."""
    offer = stubs.offers.get(body.offer_id)
    req = stubs.offer_request(body.offer_id.rsplit(":", 1)[0])
    if offer is None or req is None:
        raise not_found("offer")
    if body.replace_line_id == 0:
        draft = LineDraft.from_offers_request(req, "ui", product_id=offer.product_id)
        return added(baskets.add_lines(buyer, basket_id, [draft], dedupe=True))
    if basket_id == "new":
        raise HTTPException(422, "replace_line_id needs an existing basket_id")
    return changed(baskets.choose_product(buyer, basket_id, body.replace_line_id, offer.product_id))
