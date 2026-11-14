/**
 * Client tools: UI only, ids only (PLAN M13.5). Components fetch the data from the gateway by id.
 * Handlers return strings instead of throwing: a throw also fires onError.
 */
import { useEffect, useRef } from "react";
import { useConversationClientTool } from "@elevenlabs/react";
import { api, type ConfirmResponse } from "../api";
import { refreshBasket } from "../cards/actions";
import { confirmationAnswer } from "../cards/basket";
import { focusBasket, onDisconnectEvent, optionsFor, showQuote, ui } from "./store";

const idOf = (params: Record<string, unknown>, key: string): string | null => {
  const v = params[key];
  return typeof v === "string" && v.length > 0 && v.length <= 80 ? v : null;
};

let settleConfirmation: ((answer: string) => void) | null = null;

/** Called by the on-screen Confirm and Decline buttons while the agent waits in request_buyer_confirmation. */
export async function answerConfirmation(quoteId: string, confirmed: boolean): Promise<ConfirmResponse | null> {
  if (!confirmed) {
    settleConfirmation?.("declined by the buyer");
    return null;
  }
  const r = await api.confirm(quoteId); // the buyer's own web session, never the agent
  settleConfirmation?.(confirmationAnswer(r, quoteId));
  return r;
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
    ui.set((s) => optionsFor(s, id, params.line_id)); // with a line_id the cards offer "Replace line N"
    return "shown";
  });
  useConversationClientTool("show_basket", (params) => {
    const id = idOf(params, "basket_id");
    if (!id) return "error: basket_id is required";
    const inFocus = ui.get().basketId === id;
    ui.set((s) => focusBasket(s, id)); // a basket coming into focus is fetched by its card
    if (inFocus) void refreshBasket(id); // the agent just changed it: show the gateway's latest answer
    return "shown";
  });
  useConversationClientTool("show_quote", (params) => {
    const id = idOf(params, "quote_id");
    if (!id) return "error: quote_id is required";
    ui.set((s) => showQuote(s, id));
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
    const done = ui.get().order;
    if (done?.quoteId === id) {
      // Ordered on screen before the call: a second place_order would be a second order.
      return `cancelled: the buyer already placed this order on screen (order_id ${done.orderId ?? "unknown"}). Call get_order for its status.`;
    }
    return new Promise<string>((resolve) => {
      pending.current = resolve;
      settleConfirmation = (a) => settle(a);
      ui.set((s) => ({ ...showQuote(s, id), confirmQuoteId: id }));
    });
  });

  // The quote waiting for confirmation left the screen (a new quote or another basket): tell the agent.
  useEffect(() => {
    const unsubscribe = ui.subscribe(() => {
      const s = ui.get();
      if (pending.current && (s.confirmQuoteId === null || s.quoteId !== s.confirmQuoteId)) {
        settle("cancelled: the quote on screen changed. Call quote_basket or show_quote again before asking.");
      }
    });
    return () => {
      unsubscribe();
    };
  }, []);
  useEffect(() => onDisconnectEvent(() => settle("cancelled: call ended")), []);
  useEffect(() => () => settle("cancelled: screen closed"), []);
  return null;
}
