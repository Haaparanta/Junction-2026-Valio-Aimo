/** Gateway-shaped test data (tests only). Values mirror the W-03 stubs; nothing here is computed. */
import type { Basket, BasketLine, BasketResponse, Offer, Quote } from "../api";

export function offer(over: Partial<Offer> = {}): Offer {
  return {
    offer_id: "OS-60674F07:464306", tier: "best", product_id: "464306", name_fi: "Valio Arki Eila 1 l", api_unit: "ST",
    qty: 1000, content_total: "1000", unit_price_net: "1.01", total_net: "1010.00", price_per_base_unit: "1.01",
    base_unit: "L", delivery_date: "2026-11-16", order_by: "2026-11-15T17:00:00+02:00", stock: "untracked",
    stock_qty: null, flags: [], explanation: { fi: "", en: "" }, ...over,
  };
}

export function line(over: Partial<BasketLine> = {}): BasketLine {
  return {
    line_id: 1, source: "voice", need_text: "1000 L laktoositonta maitoa", raw_text: null, confidence: null,
    product_id: "464306", name_fi: "Valio Arki Eila 1 l", amount: 1000, unit: "L", need_date: "2026-11-16",
    offer: offer(), alternatives: [], status: "priced", flags: [], flag_notes: [], message: { fi: "", en: "" },
    overshoot: "0", vat_rate: "14", line_vat: "141.40", line_gross: "1151.40", notes: [], ...over,
  };
}

export function basket(over: Partial<Basket> = {}): Basket {
  return {
    basket_id: "B-0A1B2C3D4E", buyer_id: "chef", status: "open", version: 1, lines: [line()],
    counts: { priced: 1 }, total_net: "1010.00", total_vat: "141.40", total_gross: "1151.40", quote_id: "",
    quote_stale: false, dishes: [], created_at: "2026-11-14T15:00:00+02:00", updated_at: "2026-11-14T15:00:00+02:00",
    ...over,
  };
}

export function basketResponse(b: Basket, changed: BasketLine | null = null, over: Partial<BasketResponse> = {}): BasketResponse {
  return {
    status: "ok", reason_code: null, message_for_user: { fi: "", en: "" }, warnings: [], basket_id: b.basket_id,
    basket: b, line: changed, ...over,
  };
}

export function quote(over: Partial<Quote> = {}): Quote {
  return {
    quote_id: "Q-1A2B3C4D5E", status: "ready_for_complete", lines: [], total_net: "1010.00", total_vat: "141.40",
    total_gross: "1151.40", delivery_date: "2026-11-16", basket_id: "B-0A1B2C3D4E", basket_version: 1,
    issued_at: "2026-11-14T15:00:00+02:00", expires_at: "2026-11-15T17:00:00+02:00", confirmed: false, quote_jws: null,
    evidence: { stub: true, api_time_now: null }, ...over,
  };
}
