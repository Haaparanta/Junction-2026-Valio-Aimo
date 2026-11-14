/**
 * Pure helpers for the basket, option and quote cards: labels, checks and ids. They never compute a price, a total,
 * VAT, a unit count, an overshoot, a date or a cut-off: those are rendered as the gateway sent them.
 */
import type { Basket, BasketLine, LineStatus, Quote } from "../api";

export const STATUS_TEXT: Record<LineStatus, string> = {
  priced: "Priced",
  needs_choice: "Choose a product",
  needs_amount: "Needs an amount",
  unmatched: "Not found",
  not_deliverable: "Not deliverable",
  cutoff_passed: "Cut-off passed",
};

/** Lines that need the buyer first, then the priced ones (the order of the counts). */
export const STATUS_ORDER: LineStatus[] = [
  "needs_choice", "needs_amount", "unmatched", "cutoff_passed", "not_deliverable", "priced",
];

export const statusLabel = (status: string): string =>
  STATUS_TEXT[status as LineStatus] ?? status.replace(/_/g, " ");

export const needsAttention = (status: string): boolean => status !== "priced";

export const FLAG_TEXT: Record<string, string> = {
  STOCK_UNTRACKED: "stock not tracked", NET_PRICE: "your contract price", VARIANT: "variant", CUTOFF_PASSED: "cut-off passed",
  PARTIAL_STOCK: "partial stock", NOT_DELIVERABLE: "not deliverable", UNIT_MISMATCH: "unit differs from catalogue",
  OUT_OF_STOCK: "out of stock", SALES_BLOCKED: "sales blocked",
  PRICE_NOT_VALID_FOR_DELIVERY_DATE: "price not valid for that date",
};

export const flagLabel = (code: string): string => FLAG_TEXT[code] ?? code.replace(/_/g, " ").toLowerCase();

/** The gateway's explanation of one flag on a line, in English, or "" when it sent none. */
export const flagNote = (l: Pick<BasketLine, "flag_notes">, code: string): string =>
  l.flag_notes.find((n) => n.code === code)?.text.en ?? "";

/** "Choose a product: 1 · Priced: 2", from the gateway's line counts per status; zero counts are left out. */
export function countsText(counts: Record<string, number>): string {
  const known = STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0);
  const other = Object.keys(counts).filter((s) => !STATUS_ORDER.includes(s as LineStatus) && (counts[s] ?? 0) > 0);
  return [...known, ...other].map((s) => `${statusLabel(s)}: ${counts[s]}`).join(" · ");
}

/**
 * A basket quote is stale when the gateway says its basket changed after it (Basket.quote_stale for that quote).
 * A single-offer quote has no basket and is never stale.
 */
export function quoteIsStale(
  q: Pick<Quote, "quote_id" | "basket_id">,
  b: Pick<Basket, "basket_id" | "quote_id" | "quote_stale"> | null,
): boolean {
  return !!q.basket_id && !!b && b.basket_id === q.basket_id && b.quote_id === q.quote_id && b.quote_stale;
}

/** The DOM id of a basket line's row, for focus and scrolling. */
export const lineDomId = (lineId: number) => `basket-line-${lineId}`;

/** What "Ask Aino to order" sends during a call: the quote id only, never a price. */
export const orderRequestMessage = (quoteId: string) => `Please place the order for quote ${quoteId}.`;

/** The buyer's amount as typed in Finland: a decimal comma, no grouping ("2,5", "1000"). Empty when none yet. */
export const formatAmount = (n: number | null): string => (n === null ? "" : String(n).replace(".", ","));

/**
 * What request_buyer_confirmation answers the agent after the on-screen Confirm. It starts with "confirmed",
 * "declined" or "cancelled", as the client tool's description promises; quote_stale asks for a new quote.
 */
export function confirmationAnswer(
  r: { confirmed: boolean; confirmation_ref: string | null; reason_code: string | null }, quoteId: string,
): string {
  if (r.confirmed) return `confirmed, gateway reference ${r.confirmation_ref ?? quoteId}`;
  if (r.reason_code === "quote_stale") {
    return "cancelled: the basket changed after this quote (quote_stale). Call quote_basket for a new quote.";
  }
  return `declined: not confirmed (${r.reason_code ?? "no reason given"})`;
}
