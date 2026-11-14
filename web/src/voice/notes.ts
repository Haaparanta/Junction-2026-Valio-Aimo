/**
 * Silent notes for the agent when a click changed the basket during a call (docs/basket-plan.md M24.6), so the agent
 * never speaks about stale numbers. Built only from the gateway's answer: line numbers, amounts, units, dates,
 * statuses, ids and totals, each checked against its shape and dropped when it does not fit. Never a product name,
 * the buyer's words or any other free text: those reach the LLM as instructions otherwise.
 */
import type { Basket, BasketLine, BasketQuoteResponse } from "../api";
import type { LineChange } from "../cards/basket";

export type BasketChange = "amount" | "date" | "offer" | "add" | "replace" | "remove" | "restore";

const ID = /^[A-Za-z0-9][A-Za-z0-9:_-]{0,79}$/;
const PRODUCT_ID = /^\d{6}$/;
const MONEY = /^\d{1,9}(\.\d{1,2})?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const API_UNIT = /^[A-Z]{1,6}$/;
const UNITS = new Set(["L", "KG", "PCS"]);
const STATUSES = new Set(["priced", "needs_choice", "needs_amount", "unmatched", "not_deliverable", "cutoff_passed"]);

const ok = (re: RegExp, v: unknown): string | null => (typeof v === "string" && re.test(v) ? v : null);
const lineNo = (n: unknown): number | null => (typeof n === "number" && Number.isInteger(n) && n > 0 && n <= 10_000 ? n : null);
const num = (n: unknown): string | null => (typeof n === "number" && Number.isFinite(n) && n > 0 && n <= 1_000_000 ? String(n) : null);

/** Which kind of change a PATCH made, for the note's wording. */
export const changeKind = (c: LineChange): BasketChange => (c.offer_id ? "offer" : c.need_date ? "date" : "amount");

/** "20 KG, delivery 2026-11-17 (40 × ST)" plus the status when the line is not priced. */
function lineFacts(l: BasketLine | null | undefined, withProduct: boolean): string {
  if (!l) return "";
  const parts: string[] = [];
  const pid = withProduct ? ok(PRODUCT_ID, l.product_id) : null;
  if (pid) parts.push(`product ${pid}`);
  const amount = num(l.amount);
  const unit = typeof l.unit === "string" && UNITS.has(l.unit) ? l.unit : null;
  if (amount && unit) parts.push(`${amount} ${unit}`);
  const date = ok(DATE, l.need_date);
  if (date) parts.push(`delivery ${date}`);
  let text = parts.join(", ");
  const qty = typeof l.offer?.qty === "number" && Number.isInteger(l.offer.qty) && l.offer.qty > 0 ? l.offer.qty : null;
  const apiUnit = ok(API_UNIT, l.offer?.api_unit);
  if (qty && apiUnit) text += ` (${qty} × ${apiUnit})`;
  const status = typeof l.status === "string" && STATUSES.has(l.status) ? l.status : null;
  if (status && status !== "priced") text += `${text ? ", " : ""}status ${status}`;
  return text;
}

/** "basket B-0A1B2C3D4E total EUR 642.10 excl. VAT" (priced lines only, as the gateway counts it). */
function basketFacts(b: Basket): string {
  const id = ok(ID, b.basket_id);
  const total = ok(MONEY, b.total_net);
  const head = id ? `basket ${id}` : "the basket";
  return total ? `${head} total EUR ${total} excl. VAT` : head;
}

/**
 * The note after a click changed line `lineId` of basket `b` (the gateway's answer); `changed` is the answer's line.
 * Example: "Buyer changed line 2 to 20 KG, delivery 2026-11-17; basket B-0A1B2C3D4E total EUR 642.10 excl. VAT."
 */
export function basketNote(kind: BasketChange, lineId: number, b: Basket, changed?: BasketLine | null): string | null {
  const n = lineNo(lineId);
  if (n === null || !b || !Array.isArray(b.lines)) return null;
  const l = changed && changed.line_id === n ? changed : b.lines.find((x) => x.line_id === n);
  const facts = (withProduct: boolean) => lineFacts(l, withProduct);
  const tail = basketFacts(b);
  switch (kind) {
    case "amount":
    case "date":
      return `Buyer changed line ${n} to ${facts(false) || "new values"}; ${tail}.`;
    case "offer":
      return `Buyer switched line ${n} to another product: ${facts(true) || "see get_basket"}; ${tail}.`;
    case "add":
      return `Buyer added line ${n} from the option cards: ${facts(true) || "see get_basket"}; ${tail}.`;
    case "replace":
      return `Buyer replaced the product on line ${n} from the option cards: ${facts(true) || "see get_basket"}; ${tail}.`;
    case "remove":
      return `Buyer removed line ${n}; ${tail}, ${b.lines.length === 1 ? "1 line" : `${b.lines.length} lines`} left.`;
    case "restore":
      return `Buyer restored line ${n}: ${facts(false) || "see get_basket"}; ${tail}.`;
  }
}

/** The note after the buyer asked for one quote on screen. */
export function quoteNote(r: BasketQuoteResponse): string | null {
  const basket = ok(ID, r.basket_id);
  const quote = ok(ID, r.quote_id);
  if (!basket) return null;
  if (r.reason_code === "basket_incomplete") {
    const open = (Array.isArray(r.open_lines) ? r.open_lines : []).map(lineNo).filter((x): x is number => x !== null);
    return `Buyer asked for one quote for basket ${basket}, but ${
      open.length ? `lines ${open.join(", ")} need` : "some lines need"} attention first (basket_incomplete).`;
  }
  if (!quote) return null;
  const total = ok(MONEY, r.total_net);
  return `Buyer made quote ${quote} for basket ${basket} on screen${total ? `: total EUR ${total} excl. VAT` : ""}. ` +
    "It is not confirmed yet.";
}
