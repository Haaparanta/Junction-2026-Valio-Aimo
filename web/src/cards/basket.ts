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
 * A basket quote is stale when its basket changed after it: the gateway flags it (Basket.quote_stale for that
 * quote), or the basket's version is no longer the one the quote priced (Quote.basket_version). Only the quote's own
 * basket can tell; a single-offer quote has no basket and is never stale.
 */
export function quoteIsStale(
  q: Pick<Quote, "quote_id" | "basket_id"> & Partial<Pick<Quote, "basket_version">>,
  b: Pick<Basket, "basket_id" | "quote_id" | "quote_stale"> & Partial<Pick<Basket, "version">> | null,
): boolean {
  if (!q.basket_id || !b || b.basket_id !== q.basket_id) return false;
  if (b.quote_id === q.quote_id && b.quote_stale) return true;
  const priced = q.basket_version;
  return typeof priced === "number" && typeof b.version === "number" && b.version !== priced;
}

/** A line's price as the gateway sent it, for the price popover; null while the line is not priced. */
export type PriceBreakdown = {
  qty: number; apiUnit: string; unitPriceNet: string; totalNet: string; vatRate: string; vat: string; gross: string;
  perBase: string; baseUnit: string;
};
export function priceBreakdown(l: Pick<BasketLine, "status" | "offer" | "vat_rate" | "line_vat" | "line_gross">):
  PriceBreakdown | null {
  const o = l.offer;
  if (l.status !== "priced" || !o || l.vat_rate === null || l.line_vat === null || l.line_gross === null) return null;
  return {
    qty: o.qty, apiUnit: o.api_unit, unitPriceNet: o.unit_price_net, totalNet: o.total_net, vatRate: l.vat_rate,
    vat: l.line_vat, gross: l.line_gross, perBase: o.price_per_base_unit, baseUnit: o.base_unit,
  };
}

/** What a status chip's popover says to do next, by status; "" when nothing is needed. */
export function nextStep(l: Pick<BasketLine, "status" | "alternatives">): string {
  switch (l.status) {
    case "needs_choice": {
      const n = l.alternatives.length;
      return n > 0
        ? `Open the product name and choose one of the ${n === 1 ? "match" : `${n} matches`}.`
        : "Open the product name and choose a product.";
    }
    case "needs_amount": return "Type the amount and choose its unit in the Amount field.";
    case "unmatched": return "Remove the line, or say or type what you meant with other words.";
    case "not_deliverable": return "Pick another delivery date, or open the product name and choose another product.";
    case "cutoff_passed": return "Pick a later delivery date.";
    default: return "";
  }
}

/** One chip's popover: its title, the gateway's explanation, and the next step. code "status" is the status chip. */
export type ChipInfo = { title: string; explanation: string; next: string };
export function chipInfo(
  l: Pick<BasketLine, "status" | "flag_notes" | "message" | "alternatives">, code: string,
): ChipInfo {
  const attention = needsAttention(l.status);
  if (code === "status") {
    return { title: statusLabel(l.status), explanation: l.message.en, next: nextStep(l) };
  }
  return {
    title: flagLabel(code),
    explanation: flagNote(l, code) || "The gateway sent no explanation for this flag.",
    next: attention ? l.message.en || nextStep(l) : "",
  };
}

/** The unit popover: the unit the gateway orders in next to the catalogue's sales unit, and UNIT_MISMATCH's note. */
export type UnitView = { apiUnit: string | null; catalogueUnit: string | null; mismatch: boolean; note: string };
export function unitView(
  l: Pick<BasketLine, "offer" | "flags" | "flag_notes">, salesUnit: string | null,
): UnitView {
  const mismatch = l.flags.includes("UNIT_MISMATCH");
  return { apiUnit: l.offer?.api_unit ?? null, catalogueUnit: salesUnit, mismatch, note: mismatch ? flagNote(l, "UNIT_MISMATCH") : "" };
}

/** An approval reason, "OVER_ORDER_CAP: EUR 1010.00 is above …": a plain title, the detail and the code. */
export type ReasonView = { code: string; title: string; detail: string };
export const REASON_TEXT: Record<string, string> = {
  OVER_ORDER_CAP: "Over your order cap", OVER_REQUISITION_CAP: "Over the cap for one delivery day",
  OVER_WEEKLY_BUDGET: "Over the weekly budget", OVER_BUDGET: "Over the weekly budget",
  QTY_OVER_MAX: "Quantity over your limit", CATEGORY_NOT_ALLOWED: "Category not in your mandate",
  TEMPERATURE_NOT_ALLOWED: "Temperature class not in your mandate", DELIVERY_DAY_NOT_ALLOWED: "Delivery day not allowed",
  SUBSTITUTION: "Includes a substitute", NET_ABOVE_LIST: "Contract price above list price",
  PRICE_JUMP: "Price jump since your last order", UNIT_MISMATCH: "Unit differs from the catalogue",
  ALLERGEN_DATA_UNKNOWN: "Allergen data unknown", MANDATE_REQUIRES_APPROVAL: "Every order needs approval",
  PRICE_CHANGED: "Price changed since the quote", OUT_OF_STOCK: "Out of stock",
  NO_MANDATE: "No mandate", ORDERS_NOT_ALLOWED: "Ordering not allowed", ALLERGEN_CONFLICT: "Allergen conflict",
  MANDATE_INVALID: "Mandate signature invalid",
};
export function parseReason(text: string): ReasonView {
  const m = /^([A-Z][A-Z0-9_]{1,60})(?::\s*([\s\S]*))?$/.exec(text.trim());
  if (!m) return { code: "", title: text, detail: "" };
  const code = m[1] ?? "";
  return { code, title: REASON_TEXT[code] ?? code.replace(/_/g, " ").toLowerCase(), detail: (m[2] ?? "").trim() };
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

/**
 * The change a unit pick makes: the new unit with the current amount (the typed one when it reads, else the line's).
 * Null when there is no amount yet: the buyer types one and that commit carries the unit.
 */
export function unitChange(l: Pick<BasketLine, "amount" | "unit">, unit: Unit, typed: number | null): LineChange | null {
  const amount = typed ?? l.amount;
  if (amount === null || amount <= 0) return null;
  if (unit === l.unit && amount === l.amount) return null;
  return { amount, unit };
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
