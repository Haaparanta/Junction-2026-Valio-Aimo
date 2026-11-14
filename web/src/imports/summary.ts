/**
 * The import summary (docs/basket-plan.md M25.5, M28.5), built only from the gateway's counts and rows:
 * "12 rows: 9 priced, 2 need your choice, 1 not found", in English and Finnish, and the rows that need attention
 * first. Nothing here matches, prices or counts units; it words what the gateway decided.
 */
import type { Confidence, ImportResponse, ImportRow } from "../api";

export type RowStatus = ImportRow["status"];

/** The order of the statuses in the summary line: priced first, then the ones that need the buyer. */
export const STATUS_ORDER: readonly RowStatus[] = [
  "priced", "needs_choice", "needs_amount", "unmatched", "not_deliverable", "cutoff_passed", "invalid",
];

// English [one, many] and Finnish (a Finnish verb after a number stays singular: "2 odottaa valintaasi").
const PHRASES: Record<RowStatus, { en: readonly [string, string]; fi: string }> = {
  priced: { en: ["priced", "priced"], fi: "hinnoiteltu" },
  needs_choice: { en: ["needs your choice", "need your choice"], fi: "odottaa valintaasi" },
  needs_amount: { en: ["needs an amount", "need an amount"], fi: "määrä puuttuu" },
  unmatched: { en: ["not found", "not found"], fi: "ei löytynyt" },
  not_deliverable: { en: ["not deliverable", "not deliverable"], fi: "ei toimitettavissa" },
  cutoff_passed: { en: ["past the order cut-off", "past the order cut-off"], fi: "tilausaika umpeutunut" },
  invalid: { en: ["could not be read", "could not be read"], fi: "ei luettavissa" },
};

/** The text on a row's status chip. */
export const STATUS_CHIP: Record<RowStatus, string> = {
  priced: "Priced",
  needs_choice: "Needs choice",
  needs_amount: "Needs amount",
  unmatched: "Not found",
  not_deliverable: "Not deliverable",
  cutoff_passed: "Cut-off passed",
  invalid: "Invalid row",
};

export const CONFIDENCE_CHIP: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const isStatus = (s: string): s is RowStatus => (STATUS_ORDER as readonly string[]).includes(s);

/** The statuses with rows, in STATUS_ORDER; a status this page does not know yet comes last, as its code. */
function present(counts: Record<string, number>): [string, number][] {
  const positive = (s: string) => Number.isInteger(counts[s]) && (counts[s] ?? 0) > 0;
  const known = STATUS_ORDER.filter(positive);
  const other = Object.keys(counts).filter((s) => !isStatus(s) && positive(s)).sort();
  return [...known, ...other].map((s) => [s, counts[s] ?? 0]);
}

export type SummaryText = { en: string; fi: string };

/** "12 rows: 9 priced, 2 need your choice, 1 not found" and the same in Finnish, from ImportResponse.counts. */
export function summaryText(counts: Record<string, number>): SummaryText {
  const parts = present(counts);
  const total = parts.reduce((sum, [, n]) => sum + n, 0);
  if (total === 0) return { en: "No rows were imported", fi: "Yhtään riviä ei tuotu" };
  const en = parts.map(([s, n]) => `${n} ${isStatus(s) ? PHRASES[s].en[n === 1 ? 0 : 1] : s.replaceAll("_", " ")}`);
  const fi = parts.map(([s, n]) => `${n} ${isStatus(s) ? PHRASES[s].fi : s.replaceAll("_", " ")}`);
  return {
    en: `${total} ${total === 1 ? "row" : "rows"}: ${en.join(", ")}`,
    fi: `${total} ${total === 1 ? "rivi" : "riviä"}: ${fi.join(", ")}`,
  };
}

export const needsAttention = (row: ImportRow): boolean => row.status !== "priced";

/** Rows that need the buyer first, then the priced ones; the gateway's order is kept inside each group. */
export function attentionFirst(rows: readonly ImportRow[]): ImportRow[] {
  return [...rows.filter(needsAttention), ...rows.filter((r) => !needsAttention(r))];
}

/**
 * How sure the photo reading of a row was: the extraction item at the row's place (or with the same text), else
 * the basket line's own confidence. Null for sheet rows, which have neither.
 */
export function confidenceFor(row: ImportRow, response: ImportResponse): Confidence | null {
  const items = response.extraction?.items ?? [];
  const atPlace = items[row.row_number - 1];
  const item = atPlace?.raw_text === row.raw_text ? atPlace : items.find((i) => i.raw_text === row.raw_text);
  if (item) return item.confidence;
  if (row.line_id === null) return null;
  return response.basket.lines.find((l) => l.line_id === row.line_id)?.confidence ?? null;
}

/** Why a row has no basket line, and what the buyer can do about it. */
export const notAddedText = (photo: boolean): string =>
  photo
    ? "Not added to the basket: send a clearer photo, or add it by voice or chat."
    : "Not added to the basket: fix the row in the file and import it again, or add it by voice or chat.";
