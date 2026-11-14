/** Basket actions shared by the cards: each sends one gateway call and puts the gateway's answer in the store. */
import { api, errorText, type BasketQuoteResponse, type BasketResponse } from "../api";
import { focusBasket, receiveBasket, showQuote, showToast, ui } from "../voice/store";
import { lineDomId } from "./basket";
import { showBasketLine } from "./highlight";

/** Focus an element as soon as it exists: cards render after their own fetch. */
export function focusSoon(id: string, tries = 90): void {
  const el = typeof document === "undefined" ? null : document.getElementById(id);
  if (el) {
    el.focus(); // scrolls it into view as well
    return;
  }
  if (tries > 0 && typeof requestAnimationFrame === "function") requestAnimationFrame(() => focusSoon(id, tries - 1));
}

/** Does a 200 answer carry a basket? The gateway is built in parallel, so check before trusting it. */
export const hasBasket = (r: Partial<BasketResponse> | null | undefined): r is BasketResponse =>
  !!r && !!r.basket && typeof r.basket.basket_id === "string" && Array.isArray(r.basket.lines);

/** Put a basket answer for the basket in focus into the store. */
export function applyBasket(r: Partial<BasketResponse> | null | undefined): void {
  if (hasBasket(r)) ui.set((s) => receiveBasket(s, r.basket));
}

/** Undo for a removed line (the toast's action): POST …/restore, then focus the line that came back. */
export async function restoreLine(basketId: string, lineId: number): Promise<BasketResponse | null> {
  try {
    const r = await api.restoreLine(basketId, lineId);
    applyBasket(r);
    ui.set(showToast(r.reason_code ? r.message_for_user.en : `Line ${lineId} is back.`));
    if (!r.reason_code) focusSoon(lineDomId(lineId));
    return r;
  } catch (e) {
    ui.set(showToast(`Could not bring line ${lineId} back: ${errorText(e)}`));
    return null;
  }
}

/** Fetch the basket again, after a quote or an order changed it on the gateway. */
export async function refreshBasket(basketId: string): Promise<void> {
  try {
    applyBasket(await api.basket(basketId));
  } catch {
    /* the card keeps the last answer */
  }
}

/**
 * One quote for the whole basket. A new quote goes on screen (and gets focus); with basket_incomplete the open
 * lines are marked and focus moves to the first of them. Every answer is returned, for the caller's message.
 */
export async function quoteBasketNow(basketId: string): Promise<BasketQuoteResponse> {
  const r = await api.quoteBasket(basketId);
  if (r.reason_code === "basket_incomplete") {
    const lines = Array.isArray(r.open_lines) ? r.open_lines : [];
    ui.set({ basketAlert: { basketId, lines, message: r.message_for_user.en } });
    if (lines[0] !== undefined) focusSoon(lineDomId(lines[0]));
  } else if (r.quote_id) {
    const quoteId = r.quote_id;
    ui.set((s) => ({ ...showQuote(s, quoteId, r.basket_id || basketId), basketAlert: null }));
    focusSoon(`quote-${quoteId}`);
    void refreshBasket(basketId);
  }
  return r;
}

/**
 * Scroll to basket line `lineId` and highlight it (a quote line or an import summary row). The basket comes into
 * focus first when it is another one; a line that is not on screen any more gets a toast.
 */
export function goToBasketLine(basketId: string | null, lineId: number): void {
  if (basketId && ui.get().basketId !== basketId) ui.set((s) => focusBasket(s, basketId));
  void showBasketLine(lineId, {
    onMissing: () => ui.set(showToast(`Line ${lineId} is not in the basket on screen any more.`)),
  });
}
