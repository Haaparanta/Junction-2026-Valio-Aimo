import { describe, expect, it } from "vitest";
import { basket, line, offer, quote } from "../testing/fixtures";
import {
  allergenLabel, buildPatch, chipFlags, claimLabel, confirmationAnswer, countsText, flagLabel, flagNote, formatAmount, isIsoDate,
  MAX_AMOUNT, needsAttention, orderRequestMessage, parseAmount, quoteIsStale, refusal, statusLabel, stepAmount,
  chipInfo, nextStep, parseReason, priceBreakdown, unitView,
} from "./basket";

describe("status and flag labels", () => {
  it("names every line status, and falls back to the code for a new one", () => {
    expect(statusLabel("priced")).toBe("Priced");
    expect(statusLabel("needs_choice")).toBe("Choose a product");
    expect(statusLabel("needs_amount")).toBe("Needs an amount");
    expect(statusLabel("unmatched")).toBe("Not found");
    expect(statusLabel("not_deliverable")).toBe("Not deliverable");
    expect(statusLabel("cutoff_passed")).toBe("Cut-off passed");
    expect(statusLabel("on_hold")).toBe("on hold");
  });
  it("every status but priced needs the buyer", () => {
    expect(needsAttention("priced")).toBe(false);
    for (const s of ["needs_choice", "needs_amount", "unmatched", "not_deliverable", "cutoff_passed"]) {
      expect(needsAttention(s)).toBe(true);
    }
  });
  it("labels flags in plain words, unknown ones from their code", () => {
    expect(flagLabel("UNIT_MISMATCH")).toBe("unit differs from catalogue");
    expect(flagLabel("PRICE_NOT_VALID_FOR_DELIVERY_DATE")).toBe("price not valid for that date");
    expect(flagLabel("NEW_FLAG")).toBe("new flag");
  });
  it("leaves out the flag chip that only repeats the status chip", () => {
    expect(chipFlags(line({ status: "cutoff_passed", flags: ["CUTOFF_PASSED", "VARIANT"] }))).toEqual(["VARIANT"]);
    expect(chipFlags(line({ status: "not_deliverable", flags: ["NOT_DELIVERABLE"] }))).toEqual([]);
    expect(chipFlags(line({ status: "priced", flags: ["CUTOFF_PASSED"] }))).toEqual(["CUTOFF_PASSED"]);
  });
  it("takes a flag's explanation from the gateway's flag_notes", () => {
    const l = line({ flags: ["VARIANT"], flag_notes: [{ code: "VARIANT", text: { fi: "Muunnos", en: "A milk drink, not milk." } }] });
    expect(flagNote(l, "VARIANT")).toBe("A milk drink, not milk.");
    expect(flagNote(l, "PARTIAL_STOCK")).toBe("");
  });
  it("lists the gateway's counts, open statuses first, without zeros", () => {
    expect(countsText({ priced: 2, needs_choice: 1, unmatched: 0 })).toBe("Choose a product: 1 · Priced: 2");
    expect(countsText({ priced: 3, on_hold: 1 })).toBe("Priced: 3 · on hold: 1");
    expect(countsText({})).toBe("");
  });
});

describe("stale quotes", () => {
  it("a basket quote is stale when the gateway marks its basket changed", () => {
    const q = quote({ quote_id: "Q-1", basket_id: "B-0A1B2C3D4E" });
    expect(quoteIsStale(q, basket({ quote_id: "Q-1", quote_stale: true }))).toBe(true);
    expect(quoteIsStale(q, basket({ quote_id: "Q-1", quote_stale: false }))).toBe(false);
  });
  it("is not stale for another basket, an unknown basket, a newer quote, or a single-offer quote", () => {
    const q = quote({ quote_id: "Q-1", basket_id: "B-0A1B2C3D4E" });
    expect(quoteIsStale(q, basket({ basket_id: "B-FFFFFFFFFF", quote_id: "Q-1", quote_stale: true }))).toBe(false);
    expect(quoteIsStale(q, null)).toBe(false);
    expect(quoteIsStale(q, basket({ quote_id: "Q-2", quote_stale: true }))).toBe(false); // that flag is about Q-2
    expect(quoteIsStale(quote({ basket_id: null }), basket({ quote_stale: true }))).toBe(false);
  });
  it("is stale when the basket's version is no longer the one the quote priced", () => {
    const q = quote({ quote_id: "Q-1", basket_id: "B-0A1B2C3D4E", basket_version: 3 });
    expect(quoteIsStale(q, basket({ version: 4, quote_id: "Q-1", quote_stale: false }))).toBe(true);
    expect(quoteIsStale(q, basket({ version: 3, quote_id: "Q-1", quote_stale: false }))).toBe(false);
    expect(quoteIsStale(q, basket({ version: 4, quote_id: "Q-2" }))).toBe(true); // an older quote of a changed basket
    expect(quoteIsStale({ ...q, basket_version: null }, basket({ version: 9, quote_id: "Q-1" }))).toBe(false);
    expect(quoteIsStale(q, basket({ basket_id: "B-FFFFFFFFFF", version: 9 }))).toBe(false);
  });
});

describe("the price popover", () => {
  it("passes the gateway's numbers through unchanged", () => {
    const l = line({ offer: offer({ qty: 40, api_unit: "ST", unit_price_net: "25.25", total_net: "1010.00" }),
                     vat_rate: "14", line_vat: "141.40", line_gross: "1151.40" });
    expect(priceBreakdown(l)).toEqual({
      qty: 40, apiUnit: "ST", unitPriceNet: "25.25", totalNet: "1010.00", vatRate: "14", vat: "141.40", gross: "1151.40",
      perBase: "1.01", baseUnit: "L",
    });
  });
  it("has nothing to show until the gateway priced the line", () => {
    expect(priceBreakdown(line({ status: "needs_choice" }))).toBeNull();
    expect(priceBreakdown(line({ offer: null }))).toBeNull();
    expect(priceBreakdown(line({ line_gross: null }))).toBeNull();
  });
});

describe("chip popovers", () => {
  const msg = (en: string) => ({ fi: en, en });
  it("the status chip explains with the line's message and gives the next step", () => {
    const l = line({ status: "needs_choice", message: msg("3 products match."), alternatives: [offer(), offer(), offer()] });
    expect(chipInfo(l, "status")).toEqual({
      title: "Choose a product", explanation: "3 products match.",
      next: "Open the product name and choose one of the 3 matches.",
    });
    expect(chipInfo(line(), "status").next).toBe("");
  });
  it("a flag chip explains with the gateway's flag note; the next step only when the line needs the buyer", () => {
    const notes = [{ code: "PARTIAL_STOCK", text: msg("Only 600 in stock.") }];
    expect(chipInfo(line({ flags: ["PARTIAL_STOCK"], flag_notes: notes }), "PARTIAL_STOCK")).toEqual({
      title: "partial stock", explanation: "Only 600 in stock.", next: "",
    });
    const open = line({ status: "cutoff_passed", flags: ["PARTIAL_STOCK"], flag_notes: notes, message: msg("Too late.") });
    expect(chipInfo(open, "PARTIAL_STOCK").next).toBe("Too late.");
    expect(chipInfo(line({ flags: ["VARIANT"] }), "VARIANT").explanation).toMatch(/no explanation/);
  });
  it("names a next step for every status that needs the buyer", () => {
    for (const status of ["needs_amount", "unmatched", "not_deliverable", "cutoff_passed"] as const) {
      expect(nextStep({ status, alternatives: [] })).not.toBe("");
    }
    expect(nextStep({ status: "needs_choice", alternatives: [offer()] })).toMatch(/one of the match\./);
  });
});

describe("the unit popover", () => {
  it("shows the API unit next to the catalogue unit, with the UNIT_MISMATCH note", () => {
    const l = line({ flags: ["UNIT_MISMATCH"], flag_notes: [{ code: "UNIT_MISMATCH", text: { fi: "", en: "Sold per box." } }] });
    expect(unitView(l, "PAK")).toEqual({ apiUnit: "ST", catalogueUnit: "PAK", mismatch: true, note: "Sold per box." });
    expect(unitView(line(), null)).toEqual({ apiUnit: "ST", catalogueUnit: null, mismatch: false, note: "" });
  });
});

describe("approval reasons", () => {
  it("splits the code from the detail and names the code", () => {
    expect(parseReason("OVER_ORDER_CAP: EUR 1010.00 is above the 500.00 cap")).toEqual({
      code: "OVER_ORDER_CAP", title: "Over your order cap", detail: "EUR 1010.00 is above the 500.00 cap",
    });
    expect(parseReason("NEW_RULE")).toEqual({ code: "NEW_RULE", title: "new rule", detail: "" });
    expect(parseReason("a plain sentence")).toEqual({ code: "", title: "a plain sentence", detail: "" });
  });
});

describe("confirmation answers for the agent", () => {
  it("starts with confirmed, declined or cancelled", () => {
    expect(confirmationAnswer({ confirmed: true, confirmation_ref: "C-1", reason_code: null }, "Q-1"))
      .toBe("confirmed, gateway reference C-1");
    expect(confirmationAnswer({ confirmed: true, confirmation_ref: null, reason_code: null }, "Q-1"))
      .toBe("confirmed, gateway reference Q-1");
    expect(confirmationAnswer({ confirmed: false, confirmation_ref: null, reason_code: "quote_stale" }, "Q-1"))
      .toMatch(/^cancelled: .*quote_stale.*quote_basket/);
    expect(confirmationAnswer({ confirmed: false, confirmation_ref: null, reason_code: "quote_expired" }, "Q-1"))
      .toMatch(/^declined: .*quote_expired/);
  });
  it("asks the agent to order with the quote id only, never a price", () => {
    const m = orderRequestMessage("Q-1A2B3C4D5E");
    expect(m).toContain("Q-1A2B3C4D5E");
    expect(m).not.toMatch(/\d+[.,]\d{2}|€|EUR/);
  });
});

describe("amounts as the buyer types them", () => {
  it("shows a decimal comma and nothing for a missing amount", () => {
    expect(formatAmount(2.5)).toBe("2,5");
    expect(formatAmount(1000)).toBe("1000");
    expect(formatAmount(null)).toBe("");
  });
  it("reads a decimal comma or point, and spaces between thousands", () => {
    expect(parseAmount("2,5")).toBe(2.5);
    expect(parseAmount(" 2.5 ")).toBe(2.5);
    expect(parseAmount("1 000")).toBe(1000);
    expect(parseAmount("1 000,25")).toBe(1000.25);
    expect(parseAmount(",5")).toBe(0.5);
    expect(parseAmount("20")).toBe(20);
    expect(parseAmount("20,")).toBe(20);
  });
  it("refuses what is not one positive amount within the gateway's limit", () => {
    for (const bad of ["", "abc", "0", "0,0", "-3", "1,000,5", "1.2.3", "2 kg", "1e3", "1000001"]) {
      expect(parseAmount(bad)).toBeNull();
    }
    expect(parseAmount(String(MAX_AMOUNT))).toBe(MAX_AMOUNT);
  });
  it("steps the typed amount, and −/+ retrace each other", () => {
    expect(stepAmount(20, 1)).toBe(21);
    expect(stepAmount(20, -1)).toBe(19);
    expect(stepAmount(1000, 1)).toBe(1100);
    expect(stepAmount(1000, -1)).toBe(990);
    expect(stepAmount(990, 1)).toBe(1000);
    expect(stepAmount(100, -1)).toBe(99);
    expect(stepAmount(2.5, 1)).toBe(3.5);
    expect(stepAmount(1, -1)).toBeNull(); // never 0
    expect(stepAmount(0.5, -1)).toBeNull();
    expect(stepAmount(null, 1)).toBe(1);
    expect(stepAmount(null, -1)).toBeNull();
    expect(stepAmount(MAX_AMOUNT, 1)).toBeNull();
  });
});

describe("PATCH bodies", () => {
  it("always carry all four fields, with 0 and empty meaning keep", () => {
    expect(buildPatch({ amount: 20 })).toEqual({ amount: 20, unit: "", need_date: "", offer_id: "" });
    expect(buildPatch({ need_date: "2026-11-17" })).toEqual({ amount: 0, unit: "", need_date: "2026-11-17", offer_id: "" });
    expect(buildPatch({ offer_id: "OS-1:464076" })).toEqual({ amount: 0, unit: "", need_date: "", offer_id: "OS-1:464076" });
    expect(buildPatch({ amount: 5, unit: "KG" })).toEqual({ amount: 5, unit: "KG", need_date: "", offer_id: "" });
    expect(Object.keys(buildPatch({}))).toEqual(["amount", "unit", "need_date", "offer_id"]);
  });
  it("only sends a full date", () => {
    expect(isIsoDate("2026-11-17")).toBe(true);
    expect(isIsoDate("0002-11-17")).toBe(false); // half-typed year in a date input
    expect(isIsoDate("17.11.2026")).toBe(false);
    expect(isIsoDate("")).toBe(false);
  });
  it("tells a refused change from one the gateway made", () => {
    const msg = (en: string) => ({ fi: "", en });
    expect(refusal({ reason_code: null, message_for_user: msg("") })).toBeNull();
    expect(refusal({ reason_code: "cutoff_passed", message_for_user: msg("Cut-off passed.") })).toBeNull();
    expect(refusal({ reason_code: "basket_locked", message_for_user: msg("Already ordered.") })).toBe("Already ordered.");
    expect(refusal({ reason_code: "unknown_id", message_for_user: msg("") })).toMatch(/alternatives/);
    expect(refusal({ reason_code: "something_new", message_for_user: null })).toMatch(/something_new/);
  });
});

describe("product facts in plain words", () => {
  it("labels claims and GS1 allergen codes, keeping unknown codes", () => {
    expect(claimLabel("FREE_FROM_LACTOSE")).toBe("lactose-free");
    expect(claimLabel("NEW_CLAIM")).toBe("new claim");
    expect(allergenLabel("AM")).toBe("milk");
    expect(allergenLabel("GO")).toBe("oats");
    expect(allergenLabel("XX")).toBe("XX");
  });
});
