import { describe, expect, it } from "vitest";
import { basket, line, quote } from "../testing/fixtures";
import {
  confirmationAnswer, countsText, flagLabel, flagNote, formatAmount, needsAttention, orderRequestMessage, quoteIsStale,
  statusLabel,
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
});
