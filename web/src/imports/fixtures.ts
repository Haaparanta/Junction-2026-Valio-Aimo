/** Gateway answers for the *.test.ts files in this folder. Shapes follow api.ts; the values are made up. */
import type { Basket, BasketDish, BasketLine, DishResponse, ImportResponse, ImportRow, ListItem, Msg } from "../api";

export const msg = (en: string, fi = en): Msg => ({ fi, en });

export function line(over: Partial<BasketLine> & { line_id: number }): BasketLine {
  return {
    source: "import", need_text: "voi", raw_text: null, confidence: null, product_id: null, name_fi: null,
    amount: 5, unit: "KG", need_date: "2026-11-16", offer: null, alternatives: [], status: "priced", flags: [],
    flag_notes: [], message: msg("Priced."), overshoot: null, vat_rate: null, line_vat: null, line_gross: null,
    notes: [], ...over,
  };
}

export function basket(lines: BasketLine[], over: Partial<Basket> = {}): Basket {
  return {
    basket_id: "B-0A1B2C3D4E", buyer_id: "chef", status: "open", version: 4, lines, counts: {},
    total_net: "642.10", total_vat: "154.10", total_gross: "796.20", quote_id: "", quote_stale: false, dishes: [],
    created_at: "2026-11-14T10:00:00+02:00", updated_at: "2026-11-14T10:05:00+02:00", ...over,
  };
}

export function row(row_number: number, status: ImportRow["status"], line_id: number | null, raw_text = `row ${row_number}`): ImportRow {
  return { row_number, status, line_id, raw_text, message: msg(`Row ${row_number}: ${status}.`) };
}

export function item(raw_text: string, confidence: ListItem["confidence"]): ListItem {
  return { raw_text, name: raw_text, quantity: null, unit: null, note: "", confidence };
}

export function importResponse(
  rows: ImportRow[], counts: Record<string, number>, lines: BasketLine[] = [], over: Partial<ImportResponse> = {},
): ImportResponse {
  return {
    status: "ok", reason_code: null, message_for_user: msg("List imported."), warnings: [],
    basket_id: "B-0A1B2C3D4E", basket: basket(lines), rows, counts, extraction: null, ...over,
  };
}

export function dish(over: Partial<BasketDish> = {}): BasketDish {
  return {
    dish: "mansikkakakku", dish_name: msg("Strawberry cake", "Mansikkakakku"), servings: 40, need_date: "2026-11-16",
    batch_note: msg("About 5 cakes of 8 portions."), line_ids: [5, 6, 7], assumptions: [msg("A sponge cake.")],
    warnings: [], ...over,
  };
}

export function dishResponse(d: BasketDish, lines: BasketLine[], over: Partial<Basket> = {}): DishResponse {
  return {
    status: "ok", reason_code: null, message_for_user: msg("Dish planned."), warnings: [],
    basket_id: "B-0A1B2C3D4E", basket: basket(lines, { dishes: [d], ...over }), dish: d,
  };
}
