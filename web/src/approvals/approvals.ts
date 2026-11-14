/**
 * Pure helpers for approvals (PLAN M9): what a decision's answer means in plain language, what the buyer sees when
 * the order finishes, and the silent note for the agent. Every outcome is read from the gateway's status and
 * reason_code, never from text.
 */
import type { Approval, Decision, Me, Msg } from "../api";

export type Tone = "ok" | "warn" | "bad";
export type Outcome = { tone: Tone; title: string; detail: string };

/** Who decides, for the buyer: the gateway's generic role "approver" reads as "your manager". */
export const approverLabel = (role: string) => (role === "approver" ? "your manager" : role.replace(/_/g, " "));

export const isPending = (status: string) => status === "requires_escalation";
export const isFinal = (status: string) => status === "completed" || status === "canceled";

/** Which screen a session gets: the approver console for the approver role, else the buyer workspace. */
export type Screen = "loading" | "login" | "approver" | "buyer";
export function screenFor(me: Me | null | undefined): Screen {
  if (me === undefined) return "loading";
  if (me === null) return "login";
  return me.role === "approver" ? "approver" : "buyer";
}

/** The gateway's own text, when it sent one, as the detail under a plain title. */
const said = (m: Msg | null | undefined) => (m?.en ?? "").trim();

/**
 * The approver's view of the answer to a decision. Deciding twice answers the first decision unchanged, so the
 * answer can disagree with the button pressed: then it says the earlier decision stands.
 */
export function decisionMessage(decision: Decision, r: Approval): Outcome {
  const orderId = r.approval.order_id;
  const detail = said(r.message_for_user);
  if (r.reason_code === "quote_expired") {
    return { tone: "bad", title: "Too late: the decide-by time passed, so the request expired. Nothing was ordered.", detail };
  }
  if (r.reason_code === "price_changed") {
    return {
      tone: "warn",
      title: "Not ordered yet: the price or stock changed after the quote. The buyer needs a new quote.",
      detail,
    };
  }
  if (r.status === "completed") {
    // A plain approval says it all in the title; the gateway's sentence would only repeat it.
    return decision === "approve"
      ? { tone: "ok", title: `Approved. Order ${orderId} is placed.`, detail: "" }
      : { tone: "ok", title: `Already approved earlier: order ${orderId} is placed. Your earlier decision stands.`, detail };
  }
  if (r.status === "canceled") {
    const rejected = r.reason_code === "approval_rejected";
    if (rejected && decision === "approve") {
      return { tone: "bad", title: "Already rejected earlier. Your earlier decision stands.", detail };
    }
    return {
      tone: "bad",
      title: rejected ? `Rejected. Order ${orderId} is canceled and the buyer sees your comment.` : `Order ${orderId} is canceled.`,
      detail: rejected && decision === "reject" ? "" : detail, // a plain rejection: the title says it all
    };
  }
  return { tone: "warn", title: detail || "Still waiting for a decision.", detail: "" };
}

/** What the buyer sees on the approval card. comment: the approver's comment, "" when none. */
export function buyerOutcome(a: Approval): Outcome & { comment: string } {
  const comment = (a.approval.comment ?? "").trim();
  const detail = said(a.message_for_user);
  const orderId = a.approval.order_id;
  if (a.reason_code === "quote_expired") {
    return { tone: "bad", title: "The approval request expired before anyone decided.", detail, comment };
  }
  if (a.reason_code === "price_changed") {
    return { tone: "warn", title: "Approved, but the price or stock changed: make a new quote.", detail, comment };
  }
  if (a.status === "completed") return { tone: "ok", title: `Approved: order ${orderId} is placed.`, detail, comment };
  if (a.status === "canceled") {
    return {
      tone: "bad",
      title: a.reason_code === "approval_rejected" ? "Rejected by the approver." : `Order ${orderId} is canceled.`,
      detail, comment,
    };
  }
  return { tone: "warn", title: detail || "Waiting for the approver.", detail: "", comment };
}

/** The silent context for the agent when the approval changed (PLAN M9.4): ids and status only, no prices. */
export function approvalNote(a: Approval): string {
  const reason = a.reason_code ? `, reason ${a.reason_code}` : "";
  return `Order ${a.approval.order_id} status changed to ${a.status}${reason} (approval ${a.approval_id}).`;
}

/** The fixed nudge after the note: a contextual update alone does not make the agent reply. */
export const APPROVAL_NUDGE = "Is there news about my order?";

/** An approval link from the gateway, /approvals/{id}: the id, or "" for any other path. */
export function approvalIdFromPath(path: string): string {
  const m = /^\/approvals\/([A-Za-z0-9_-]{3,80})\/?$/.exec(path);
  return m?.[1] ?? "";
}

/** The comment as sent: trimmed, at most 500 characters ("" is no comment). */
export const MAX_COMMENT = 500;
export const cleanComment = (text: string) => text.trim().slice(0, MAX_COMMENT);
