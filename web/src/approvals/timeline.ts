/** The "What happened" timeline (PLAN M10.4): the order's audit entries as rows to show, oldest first. */
import { helsinki, type AuditEvent } from "../api";

export type TimelineRow = {
  key: string; seq: number; at: string; when: string; actor: string; channel: string; action: string; decision: string;
  text: string; hash: string; prevHash: string;
};

const CHANNEL: Record<string, string> = {
  voice: "Voice", mcp: "MCP", rest: "REST", ui: "Web", web: "Web", console: "Approver console", system: "Gateway",
};
const ACTION: Record<string, string> = {
  create_quote: "Quote made", quote_basket: "Basket quoted", confirm_quote: "Confirmed by the buyer",
  confirm: "Confirmed by the buyer", place_order: "Order requested", request_approval: "Approval requested",
  decide_approval: "Approval decided", approval_decision: "Approval decided", recheck: "Price and stock re-checked",
  complete_order: "Order completed", cancel_order: "Order canceled", sign_receipt: "Receipt signed",
};

/** "place_order" → "Place order" for an action or channel the table does not know. */
const humane = (s: string) => {
  const t = s.replace(/[_.]+/g, " ").trim();
  return t ? t[0]!.toUpperCase() + t.slice(1) : "";
};

export const channelLabel = (c: string) => CHANNEL[c.toLowerCase()] ?? humane(c);
export const actionLabel = (a: string) => ACTION[a.toLowerCase()] ?? humane(a);
/** The first 10 characters of a hash, enough to tell entries apart on screen. */
export const shortHash = (h: string) => h.replace(/^sha256:/, "").slice(0, 10);

function textOf(e: AuditEvent): string {
  if (typeof e.detail === "string") return e.detail;
  if (e.detail && typeof e.detail.en === "string" && e.detail.en) return e.detail.en;
  return e.summary ?? "";
}

/** Helsinki time for a timestamp; the raw text when it is not one (Intl throws on an invalid date). */
export function when(iso: string): string {
  try {
    return helsinki(iso);
  } catch {
    return iso;
  }
}

/** Sorted by seq, so the order on screen never depends on the order of arrival. */
export function timelineRows(events: AuditEvent[]): TimelineRow[] {
  return [...events].sort((a, b) => a.seq - b.seq).map((e) => ({
    key: `${e.seq}-${e.hash}`, seq: e.seq, at: e.at, when: when(e.at), actor: e.actor, channel: channelLabel(e.channel),
    action: actionLabel(e.action), decision: e.decision, text: textOf(e), hash: shortHash(e.hash),
    prevHash: shortHash(e.prev_hash),
  }));
}
