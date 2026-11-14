/**
 * Client tools: UI only, ids only (PLAN M13.5). Components fetch the data from the gateway by id.
 * Handlers return strings instead of throwing: a throw also fires onError.
 */
import { useEffect, useRef } from "react";
import { useConversationClientTool } from "@elevenlabs/react";
import { api } from "../api";
import { onDisconnectEvent, ui } from "./store";

const idOf = (params: Record<string, unknown>, key: string): string | null => {
  const v = params[key];
  return typeof v === "string" && v.length > 0 && v.length <= 80 ? v : null;
};

let settleConfirmation: ((answer: string) => void) | null = null;

/** Called by the on-screen Confirm and Decline buttons. */
export async function answerConfirmation(quoteId: string, confirmed: boolean): Promise<void> {
  if (!confirmed) {
    settleConfirmation?.("declined by the buyer");
    return;
  }
  const r = await api.confirm(quoteId); // the buyer's own web session, never the agent
  settleConfirmation?.(r.confirmed ? `confirmed, gateway reference ${r.confirmation_ref ?? quoteId}` : "declined");
}

export function ClientTools() {
  const pending = useRef<((answer: string) => void) | null>(null);

  const settle = (answer: string) => {
    pending.current?.(answer);
    pending.current = null;
    settleConfirmation = null;
    ui.set({ confirmQuoteId: null });
  };

  useConversationClientTool("show_products", (params) => {
    const id = idOf(params, "offer_set_id");
    if (!id) return "error: offer_set_id is required";
    ui.set({ offerSetId: id });
    return "shown";
  });
  useConversationClientTool("show_quote", (params) => {
    const id = idOf(params, "quote_id");
    if (!id) return "error: quote_id is required";
    ui.set({ quoteId: id });
    return "shown";
  });
  useConversationClientTool("show_approval_request", (params) => {
    const id = idOf(params, "approval_id");
    if (!id) return "error: approval_id is required";
    ui.set({ approvalId: id });
    return "shown";
  });
  useConversationClientTool("request_buyer_confirmation", (params) => {
    const id = idOf(params, "quote_id");
    if (!id) return "error: quote_id is required";
    settle("cancelled: replaced by a newer request");
    return new Promise<string>((resolve) => {
      pending.current = resolve;
      settleConfirmation = (a) => settle(a);
      ui.set({ quoteId: id, confirmQuoteId: id });
    });
  });

  useEffect(() => onDisconnectEvent(() => settle("cancelled: call ended")), []);
  useEffect(() => () => settle("cancelled: screen closed"), []);
  return null;
}
