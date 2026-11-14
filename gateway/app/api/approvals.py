"""The approver console's API (PLAN M9.1, M9.3, M9.5): the pending list and the decision, under the approver's cookie.

Only a human approver decides, on their own console: the routes take the demo-login cookie of a buyer whose role is
approver. A buyer session gets 403, and so does any call that carries the voice tool headers or an MCP bearer key, so
neither the voice agent nor an external agent can approve. GET /v1/approvals/{approval_id} stays in tools.py.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Path

from .. import audit, orders
from ..contract import ApprovalDecisionRequest, ApprovalListResponse, ApprovalResponse
from ..identity import Buyer, SettingsDep, StoreDep, web_buyer
from .common import StateDep, not_found

router = APIRouter(prefix="/approvals")
ApprovalIdPath = Annotated[str, Path(min_length=3, max_length=80, description="approval_id as returned by a tool.")]
CONSOLE_ONLY = "Approvals are decided only by an approver on the approver console."


def approver_session(
    store: StoreDep,
    va_session: Annotated[str | None, Cookie(include_in_schema=False)] = None,
    x_gateway_key: Annotated[str | None, Header(include_in_schema=False)] = None,
    x_session_token: Annotated[str | None, Header(include_in_schema=False)] = None,
    x_conversation_id: Annotated[str | None, Header(include_in_schema=False)] = None,
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
) -> Buyer:
    """The signed-in approver. Voice headers or a bearer key mean an agent is calling: 403 (M9.5)."""
    if x_gateway_key or x_session_token or x_conversation_id or authorization:
        raise HTTPException(403, CONSOLE_ONLY)
    buyer = web_buyer(store, va_session)  # 401 when not signed in
    if buyer.role != "approver":
        raise HTTPException(403, CONSOLE_ONLY)
    return buyer


ApproverDep = Annotated[Buyer, Depends(approver_session)]


@router.get("", tags=["ui"])
def list_approvals(approver: ApproverDep, stubs: StateDep, settings: SettingsDep) -> ApprovalListResponse:
    """The approver's own organisation: pending first, newest first. Requests past decide-by show as canceled."""
    return orders.list_approvals(stubs, approver, settings.as_of)


@router.post("/{approval_id}/decision", tags=["ui"])
def decide(
    approval_id: ApprovalIdPath,
    body: ApprovalDecisionRequest,
    approver: ApproverDep,
    stubs: StateDep,
    settings: SettingsDep,
) -> ApprovalResponse:
    """Approve (the order is re-checked and completes, or the approval is voided with price_changed) or reject (the
    order is canceled with approval_rejected). After decide-by it answers quote_expired. A second decision answers
    the first one unchanged."""
    try:
        res = orders.decide(stubs, approver, approval_id, body.decision, body.comment, settings.as_of)
    except orders.NotYours as e:
        raise HTTPException(403, "An approver cannot decide their own order.") from e
    if res is None:
        raise not_found("approval")
    a, o = res.approval, res.order
    audit.log(
        stubs,
        approver,
        "approval.decide",
        as_of=settings.as_of,
        response=res,
        decision=f"{body.decision} -> {a.outcome or a.status}",
        inputs={"decision": body.decision, "comment": body.comment},
        reasons=o.reasons if o and a.outcome == "voided" else a.reasons,
        tokens=(o.receipt_jws if o else None,),
        order_id=a.order_id,
        quote_id=a.quote_id,
        approval_id=a.approval_id,
        summary=f"{approver.display_name} chose {body.decision}: approval {a.outcome or a.status}, "
        f"order {o.status if o else '-'}",
    )
    return res
