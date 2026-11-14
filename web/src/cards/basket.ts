/**
 * Pure helpers for the basket, option and quote cards: labels, checks and ids. They never compute a price, a total,
 * VAT, a unit count, an overshoot, a date or a cut-off: those are rendered as the gateway sent them.
 */
import type { Basket, BasketLine, BasketLinePatch, LineStatus, Quote, Unit } from "../api";

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

/** A line's flag chips, without the one its status chip already says (cut-off passed, not deliverable). */
const SAME_AS_STATUS: Record<string, string> = { CUTOFF_PASSED: "cutoff_passed", NOT_DELIVERABLE: "not_deliverable" };
export const chipFlags = (l: Pick<BasketLine, "flags" | "status">): string[] =>
  l.flags.filter((f) => SAME_AS_STATUS[f] !== l.status);

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

/** The most a line may ask for, as in the gateway's request models (amount le=1_000_000). */
export const MAX_AMOUNT = 1_000_000;

/**
 * The buyer's typed amount: a decimal comma or point, spaces as thousands separators ("1 000", "2,5", ".5").
 * Null for anything else, zero, a negative or above MAX_AMOUNT. It is the buyer's input, not a computed number.
 */
export function parseAmount(text: string): number | null {
  const t = text.trim().replace(/[\s  ]/g, "").replace(",", ".");
  if (!/^(\d+(\.\d*)?|\.\d+)$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 && n <= MAX_AMOUNT ? n : null;
}

/** The −/+ step for an amount the buyer typed: 1 below 100, 10 below 1 000, then 100. */
const stepFor = (n: number) => (n >= 1000 ? 100 : n >= 100 ? 10 : 1);

/**
 * The buyer's next amount for −/+ (the gateway then prices it and says the units needed). Stepping down uses the
 * step just below, so +/− retrace each other (990 ↔ 1000). Null when the result would not be a valid amount.
 */
export function stepAmount(n: number | null, dir: 1 | -1): number | null {
  if (n === null) return dir > 0 ? 1 : null;
  const next = dir > 0 ? n + stepFor(n) : n - stepFor(n - 1e-9);
  const rounded = Math.round(next * 1000) / 1000;
  return rounded > 0 && rounded <= MAX_AMOUNT ? rounded : null;
}

export type LineChange = { amount?: number; unit?: "" | Unit; need_date?: string; offer_id?: string };

/** A PATCH body always carries all four fields; 0 and "" keep the current value (the schema has no optionals). */
export function buildPatch(c: LineChange): BasketLinePatch {
  return { amount: c.amount ?? 0, unit: c.unit ?? "", need_date: c.need_date ?? "", offer_id: c.offer_id ?? "" };
}

/** Reason codes that come with a change the gateway still made: the row shows the line's own status for them. */
const APPLIED_CODES = new Set(["cutoff_passed", "not_deliverable", "out_of_stock", "price_changed"]);
const REFUSED_TEXT: Record<string, string> = {
  basket_locked: "This basket is already ordered, so it cannot change. Start a new basket.",
  unknown_id: "That option is not one of this line's alternatives any more.",
};

/** The message to show when the gateway refused a basket change, or null when it took it. */
export function refusal(r: { reason_code: string | null; message_for_user?: { en: string } | null }): string | null {
  if (!r.reason_code || APPLIED_CODES.has(r.reason_code)) return null;
  return r.message_for_user?.en || REFUSED_TEXT[r.reason_code] || `The gateway did not make the change (${r.reason_code}).`;
}

/** A full YYYY-MM-DD from a date input (half-typed years such as 0002 do not count). */
export const isIsoDate = (v: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(v) && v >= "2000-01-01" && v <= "2099-12-31";

export const CLAIM_TEXT: Record<string, string> = {
  FREE_FROM_LACTOSE: "lactose-free", LOW_LACTOSE: "low-lactose", FREE_FROM_GLUTEN: "gluten-free", VEGAN: "vegan",
  VEGETARIAN: "vegetarian", FREE_FROM_EGGS: "egg-free", FREE_FROM_SOY: "soy-free", FREE_FROM_WHEAT: "wheat-free",
};
export const claimLabel = (code: string): string => CLAIM_TEXT[code] ?? code.replace(/_/g, " ").toLowerCase();

/** GS1 allergen type codes, as the catalogue declares them. */
export const ALLERGEN_TEXT: Record<string, string> = {
  AM: "milk", AE: "eggs", AW: "cereals with gluten", UW: "wheat", GB: "barley", NR: "rye", GO: "oats", AY: "soy",
  AN: "tree nuts", AP: "peanuts", AS: "sesame", AF: "fish", AC: "crustaceans", UM: "molluscs", BC: "celery",
  BM: "mustard", AU: "sulphites", NL: "lupin",
};
export const allergenLabel = (code: string): string => ALLERGEN_TEXT[code] ?? code;

export const TEMPERATURE_TEXT: Record<string, string> = {
  chilled: "chilled", frozen: "frozen", ambient: "room temperature", unknown: "not known",
};

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
