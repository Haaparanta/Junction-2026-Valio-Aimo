"""Verifiable trust (PLAN M6.3, M8.5, M10.1, M10.4): the public signing keys and the audit trail.

* GET /.well-known/jwks.json: the gateway key (quotes and order receipts) and the organisation admin key (mandates);
  scripts/verify_quote.py checks a quote or a receipt against it.
* GET /v1/audit/verify: recomputes the whole hash chain and names the first entry that does not hold.
* GET /v1/orders/{order_id}/audit: one order's events oldest first, for its buyer or an approver of the same org
  (the buyer cookie; anyone else gets 404, as for the order itself).
"""

from typing import Annotated

from fastapi import APIRouter, Path

from .. import orders, signing
from ..audit import AuditLog, AuditResponse, AuditVerifyResponse
from ..contract import Msg
from ..identity import SettingsDep, StoreDep, WebBuyerDep
from .common import StateDep, not_found

router = APIRouter()
OrderIdPath = Annotated[str, Path(min_length=3, max_length=80, description="order_id exactly as place_order returned.")]


@router.get("/.well-known/jwks.json", tags=["trust"])
def jwks() -> dict:
    """The public ES256 keys (JWK Set): the gateway key first, then the org admin key. kid is each key's RFC 7638
    thumbprint; `typ` names what the key may sign."""
    return signing.keys().jwks()


@router.get("/v1/audit/verify", tags=["ui"])
def verify_audit(buyer: WebBuyerDep, store: StoreDep) -> AuditVerifyResponse:
    """Recompute every entry's hash and link, oldest first (M10.1). Editing, removing or reordering any row makes
    ok false and names the first broken entry."""
    return AuditLog(store).verify()


@router.get("/v1/orders/{order_id}/audit", tags=["ui"])
def order_audit(
    order_id: OrderIdPath, buyer: WebBuyerDep, stubs: StateDep, store: StoreDep, settings: SettingsDep
) -> AuditResponse:
    """The order's audit timeline (M10.4): its quote, confirmation, order, approval and transcript events, and the
    imports and basket quotes of its basket, oldest first."""
    res = orders.get_order(stubs, buyer, order_id, settings.as_of)  # None: no such order, or not this caller's
    meta = stubs.order_meta.get(order_id)
    if res is None or res.order is None or meta is None:
        raise not_found("order")
    trail = AuditLog(store)
    events = trail.for_order(order_id, res.order.quote_id, meta.quote.basket_id)
    ok = trail.verify().ok
    return AuditResponse(
        order_id=order_id,
        chain_ok=ok,
        events=events,
        message_for_user=Msg(
            fi=f"Tilauksen {order_id} tapahtumat: {len(events)}." + ("" if ok else " Auditointiketju ei ole eheä."),
            en=f"{len(events)} events for order {order_id}." + ("" if ok else " The audit trail does not verify."),
        ),
        warnings=[] if ok else ["the audit trail does not verify: see GET /v1/audit/verify"],
    )
