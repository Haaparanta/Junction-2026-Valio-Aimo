/**
 * Contextual updates for the voice agent after an intake action on screen (docs/basket-plan.md M24.6, M25.5,
 * M27, M28): short factual notes, so the agent never talks about a basket it has not seen. They are built from
 * gateway fields only: ids, counts, line and row numbers, statuses, dates and the total. Product names, cell text,
 * text read from photos and dish names are data and never go into a note, so they cannot reach the agent as
 * instructions.
 */
import type { DishResponse, ImportResponse } from "../api";

// The statuses that need the buyer, in the order a note names them: [status, one, many].
const OPEN: readonly (readonly [string, string, string])[] = [
  ["needs_choice", "needs a choice", "need a choice"],
  ["needs_amount", "needs an amount", "need an amount"],
  ["unmatched", "not found", "not found"],
  ["not_deliverable", "not deliverable", "not deliverable"],
  ["cutoff_passed", "past the order cut-off", "past the order cut-off"],
];
const KNOWN = new Set(["priced", "invalid", ...OPEN.map(([s]) => s)]);
const CODE = /^[a-z_]{1,40}$/; // a status the page does not know yet is named by its code, if it looks like one

const safeId = (id: string) => (/^[A-Za-z0-9_-]{1,80}$/.test(id) ? id : "(unreadable id)");
const safeDate = (d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? d : "");
const safeMoney = (m: string) => (/^-?\d{1,12}(\.\d{1,4})?$/.test(m) ? m : "");
const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const numbered = (word: string, ns: readonly number[]) =>
  `${ns.length === 1 ? word : `${word}s`} ${[...ns].sort((a, b) => a - b).join(", ")}`;

type LineState = { line_id: number; status: string };

/** "2 need a choice (lines 4, 7)", one part per status that needs the buyer. */
function openParts(lines: readonly LineState[]): string[] {
  const other = [...new Set(lines.map((l) => l.status))].filter((s) => !KNOWN.has(s) && CODE.test(s)).sort();
  const order: (readonly [string, string, string])[] = [...OPEN, ...other.map((s) => [s, s.replaceAll("_", " "), s.replaceAll("_", " ")] as const)];
  return order.flatMap(([status, one, many]) => {
    const ids = lines.filter((l) => l.status === status).map((l) => l.line_id);
    return ids.length ? [`${count(ids.length, one, many)} (${numbered("line", ids)})`] : [];
  });
}

function listNote(response: ImportResponse, source: string): string {
  const lines = response.basket.lines.length;
  const head = `Buyer imported a list${source}: basket ${safeId(response.basket_id)} with ${count(lines, "line", "lines")}`;
  const added = response.rows.flatMap((r) => (r.line_id === null ? [] : [{ line_id: r.line_id, status: r.status }]));
  const parts = openParts(added);
  const invalid = response.rows.filter((r) => r.status === "invalid").map((r) => r.row_number);
  if (invalid.length) parts.push(`${count(invalid.length, "row", "rows")} not added (${numbered("row", invalid)})`);
  if (!parts.length) parts.push(added.length ? "every imported line is priced" : "no lines were added");
  return `${head}; ${parts.join("; ")}.`;
}

/** After an Excel or CSV import: "Buyer imported a list: basket B-… with 12 lines; 2 need a choice (lines 4, 7); …". */
export function importNote(response: ImportResponse): string {
  return listNote(response, "");
}

/** After a photo import: the same as importNote, plus how the list was written and how much could not be read. */
export function photoNote(response: ImportResponse): string {
  const read = response.extraction;
  if (response.rows.length === 0) {
    const parts = read?.unreadable.length ? `; ${count(read.unreadable.length, "part", "parts")} could not be read` : "";
    return `Buyer sent a photo of a list, but no list lines could be read${parts}; nothing was added to basket ${safeId(response.basket_id)}.`;
  }
  const note = listNote(response, " from a photo");
  if (!read) return note;
  const unreadable = read.unreadable.length ? `; ${count(read.unreadable.length, "part", "parts")} could not be read` : "";
  return `${note} The list was ${read.handwritten ? "handwritten" : "printed"}${unreadable}.`;
}

/** After the dish form: the dish's line count and lines that need the buyer, and the basket total from the gateway. */
export function dishNote(response: DishResponse): string {
  const { basket, dish } = response;
  const date = safeDate(dish.need_date);
  const ids = new Set(dish.line_ids);
  const dishLines = basket.lines.filter((l) => ids.has(l.line_id)).map((l) => ({ line_id: l.line_id, status: l.status }));
  const what = `${count(dish.servings, "serving", "servings")}${date ? `, delivery ${date}` : ""}`;
  const added = dish.line_ids.length
    ? `${count(dish.line_ids.length, "line", "lines")} added to basket ${safeId(response.basket_id)} (${numbered("line", dish.line_ids)})`
    : `no lines added to basket ${safeId(response.basket_id)}`;
  const parts = [added, ...openParts(dishLines)];
  const total = safeMoney(basket.total_net);
  const partial = basket.lines.some((l) => l.status !== "priced");
  const totalText = total ? ` Basket total EUR ${total} excl. VAT${partial ? " for the priced lines" : ""}.` : "";
  const shown = [
    dish.warnings.length ? count(dish.warnings.length, "warning", "warnings") : "",
    dish.assumptions.length ? count(dish.assumptions.length, "assumption", "assumptions") : "",
  ].filter(Boolean);
  const screen = shown.length ? ` The screen shows the dish's ${shown.join(" and ")}.` : "";
  return `Buyer planned a dish on screen for ${what}: ${parts.join("; ")}.${totalText}${screen}`;
}
