"""The audit trail (PLAN M10.1-10.3, G-09): who did what, when and why, in a form that shows any tampering.

* Append-only: one SQLite table (db.py) whose rows SQL triggers refuse to update or delete.
* Hash-chained: each entry stores the previous entry's hash, and its own hash is the SHA-256 of its RFC 8785
  canonical JSON (prev_hash included), so editing, removing or reordering any row breaks verify() from that row on.
* One helper, log(), writes every event: quotes, confirmations, orders, cancellations, approval decisions and
  expiries, basket quotes, imports and the post-call transcript link. Each event records the actor, the channel
  (voice, web, mcp, or gateway for the gateway's own moves), the conversation id, a summary of the inputs (never a
  secret, a token or a photo), the decision, the SHA-256 of the response and the as-of time of the demo clock.
* The REST route functions are the one service entry for REST, the voice webhook tools and MCP (mcp_server.py calls
  them), so they call log(); the gateway's own moves (an approval that expires) are logged where they happen.
"""

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from .contract import Envelope, Msg
from .db import Store
from .identity import Buyer, Caller
from .signing import canonical, sha256_hex

GENESIS = "0" * 64  # the prev_hash of the first entry
INDEXED = ("order_id", "quote_id", "basket_id", "conversation_id", "action")  # copied into columns for lookups


class AuditEvent(BaseModel):
    """One entry of the trail. hash = SHA-256 of the canonical JSON of every other field."""

    seq: int
    at: str  # the as-of time (demo clock) the gateway decided at
    recorded_at: str  # wall-clock UTC time the entry was written
    actor: str  # display name, e.g. 'Chef Aada (demo)' or 'Gateway'
    actor_id: str  # buyer_id, the external agent's name, or 'gateway'
    channel: str  # voice | web | mcp | gateway
    conversation_id: str | None = None
    action: str  # quote.create, quote.confirm, order.place, order.cancel, approval.decide, approval.expire, ...
    decision: str  # the outcome: a status, optionally with its reason_code ('requires_escalation/limit_exceeded')
    reason_code: str | None = None
    order_id: str | None = None
    quote_id: str | None = None
    approval_id: str | None = None
    basket_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)  # what was asked, without secrets
    reasons: list[str] = Field(default_factory=list)  # 'CODE: detail' strings from the policy or the re-check
    response_sha256: list[str] = Field(default_factory=list)  # the answer, and any JWS it carries
    detail: Msg  # what happened, in Finnish and English (the answer's message_for_user when there is one)
    summary: str  # one short English line
    prev_hash: str
    hash: str


class AuditResponse(Envelope):
    order_id: str
    chain_ok: bool  # the whole trail verifies (GET /v1/audit/verify has the details)
    events: list[AuditEvent]  # the order's events, oldest first


class AuditVerifyResponse(Envelope):
    ok: bool
    count: int  # entries checked
    first_broken_seq: int | None = None
    problem: str | None = None
    head_hash: str  # the last entry's hash (GENESIS when the trail is empty)


class AuditLog:
    """The trail in the app's SQLite store. Appends take the write lock (BEGIN IMMEDIATE), so the chain never forks."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def append(self, **fields: Any) -> AuditEvent:
        recorded = datetime.now(UTC).isoformat(timespec="milliseconds")
        with self.store.tx() as c:
            row = c.execute("SELECT seq, hash FROM audit_event ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (row[0] + 1, row[1]) if row else (1, GENESIS)
            entry = {**fields, "seq": seq, "recorded_at": recorded, "prev_hash": prev}
            body = AuditEvent.model_validate({**entry, "hash": GENESIS}).model_dump(mode="json", exclude={"hash"})
            h = sha256_hex(canonical(body))
            c.execute(
                "INSERT INTO audit_event (seq, order_id, quote_id, basket_id, conversation_id, action, entry, hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (seq, *(body.get(k) for k in INDEXED), canonical(body).decode(), h),
            )
        return AuditEvent.model_validate({**body, "hash": h})

    def verify(self) -> AuditVerifyResponse:
        """Recompute every hash and link, oldest first; report the first entry that does not hold."""
        prev, count = GENESIS, 0
        with self.store.tx("DEFERRED") as c:
            rows = c.execute(
                "SELECT seq, order_id, quote_id, basket_id, conversation_id, action, entry, hash FROM audit_event"
                " ORDER BY seq"
            ).fetchall()
        for seq, *columns, entry, stored in rows:
            count += 1
            problem = _check(seq, columns, entry, stored, prev, count)
            if problem:
                return AuditVerifyResponse(
                    ok=False,
                    count=count,
                    first_broken_seq=seq,
                    problem=problem,
                    head_hash=rows[-1][-1],
                    message_for_user=Msg(
                        fi=f"Auditointiketju katkeaa kohdassa {seq}: {problem}.",
                        en=f"The audit trail is broken at entry {seq}: {problem}.",
                    ),
                )
            prev = stored
        return AuditVerifyResponse(
            ok=True,
            count=count,
            head_hash=prev,
            message_for_user=Msg(
                fi=f"Auditointiketju on eheä: {count} merkintää.", en=f"The audit trail verifies: {count} entries."
            ),
        )

    def for_order(self, order_id: str, quote_id: str, basket_id: str | None) -> list[AuditEvent]:
        """The order's events oldest first: its own, its quote's, and its basket's (imports, basket quotes)."""
        with self.store.tx("DEFERRED") as c:
            rows = c.execute(
                "SELECT entry, hash FROM audit_event WHERE order_id = ? OR quote_id = ? OR (basket_id IS NOT NULL"
                " AND basket_id = ?) ORDER BY seq",
                (order_id, quote_id, basket_id or ""),
            ).fetchall()
        return [AuditEvent.model_validate({**json.loads(e), "hash": h}) for e, h in rows]

    def conversation_orders(self, conversation_id: str) -> list[str]:
        """The orders a voice conversation placed or tried to place, oldest first."""
        with self.store.conn() as c:
            rows = c.execute(
                "SELECT order_id, MIN(seq) FROM audit_event WHERE conversation_id = ? AND order_id IS NOT NULL"
                " AND action = 'order.place' GROUP BY order_id ORDER BY MIN(seq)",
                (conversation_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def linked(self, conversation_id: str, order_id: str, payload_sha256: str) -> bool:
        """True when this transcript (by hash) is already linked to the order: a webhook retry adds nothing."""
        with self.store.conn() as c:
            rows = c.execute(
                "SELECT entry FROM audit_event WHERE action = 'call.transcript' AND conversation_id = ?"
                " AND order_id = ?",
                (conversation_id, order_id),
            ).fetchall()
        return any(payload_sha256 in json.loads(r[0]).get("response_sha256", []) for r in rows)


def _check(seq: int, columns: list[Any], entry: str, stored: str, prev: str, position: int) -> str | None:
    try:
        body = json.loads(entry)
    except ValueError:
        return "the entry is not JSON"
    if seq != position or body.get("seq") != seq:
        return "an entry is missing or out of order"
    if body.get("prev_hash") != prev:
        return "it does not link to the entry before it"
    if sha256_hex(canonical(body)) != stored:
        return "its content does not match its hash"
    if [body.get(k) for k in INDEXED] != list(columns):
        return "its index columns differ from its content"
    return None


# ---- the one helper ------------------------------------------------------------------------------


def response_hashes(response: BaseModel | dict | None, *tokens: str | None) -> list[str]:
    out = [sha256_hex(canonical(response))] if response is not None else []
    return out + [sha256_hex(t) for t in tokens if t]


def _decision(status: str, reason_code: str | None) -> str:
    return f"{status}/{reason_code}" if reason_code else status


def log(
    sink: Any,
    who: Caller | Buyer | None,
    action: str,
    *,
    as_of: str,
    response: BaseModel | None = None,
    decision: str | None = None,
    reason_code: str | None = None,
    detail: Msg | None = None,
    summary: str = "",
    inputs: dict[str, Any] | None = None,
    reasons: list[str] | None = None,
    tokens: tuple[str | None, ...] = (),
    order_id: str | None = None,
    quote_id: str | None = None,
    approval_id: str | None = None,
    basket_id: str | None = None,
) -> AuditEvent | None:
    """Append one event. `sink` is an AuditLog or anything with an `audit` attribute holding one (the StubState);
    without one (a bare StubState in a unit test) nothing is written. `who` is the authenticated caller, a buyer on
    their web session, or None for the gateway itself. Status, reason_code and detail default to the response's."""
    trail = sink if isinstance(sink, AuditLog) else getattr(sink, "audit", None)
    if trail is None:
        return None
    if isinstance(who, Caller):
        actor, actor_id, channel, conversation = (
            who.buyer.display_name,
            who.agent_id or who.buyer.buyer_id,
            who.channel,
            who.conversation_id,
        )
    elif isinstance(who, Buyer):
        actor, actor_id, channel, conversation = who.display_name, who.buyer_id, "web", None
    else:
        actor, actor_id, channel, conversation = "Gateway", "gateway", "gateway", None
    status = getattr(response, "status", None) or "ok"
    reason_code = reason_code if reason_code is not None else getattr(response, "reason_code", None)
    msg = detail or getattr(response, "message_for_user", None) or Msg(fi=summary, en=summary)
    return trail.append(
        at=as_of,
        actor=actor,
        actor_id=actor_id,
        channel=channel,
        conversation_id=conversation,
        action=action,
        decision=decision or _decision(status, reason_code),
        reason_code=reason_code,
        order_id=order_id,
        quote_id=quote_id,
        approval_id=approval_id,
        basket_id=basket_id,
        inputs=inputs or {},
        reasons=reasons or [],
        response_sha256=response_hashes(response, *tokens),
        detail=msg,
        summary=summary or msg.en,
    )


def link_transcript(trail: AuditLog, conversation_id: str, event_type: str, payload: dict, as_of: str) -> list[str]:
    """The post-call webhook (M10.3): link the conversation's transcript (by hash, already redacted) to each order
    the conversation placed. Returns the order ids linked by this call."""
    digest = sha256_hex(canonical(payload))
    turns = payload.get("transcript")
    linked = []
    for order_id in trail.conversation_orders(conversation_id):
        if trail.linked(conversation_id, order_id, digest):
            continue
        trail.append(
            at=as_of,
            actor="ElevenLabs post-call webhook",
            actor_id="elevenlabs",
            channel="gateway",
            conversation_id=conversation_id,
            action="call.transcript",
            decision="linked",
            order_id=order_id,
            inputs={"event_type": event_type, "turns": len(turns) if isinstance(turns, list) else 0},
            response_sha256=[digest],
            detail=Msg(
                fi=f"Puhelun {conversation_id} litterointi liitettiin tilaukseen {order_id}.",
                en=f"The transcript of call {conversation_id} was linked to order {order_id}.",
            ),
            summary=f"transcript of {conversation_id} linked",
        )
        linked.append(order_id)
    return linked
