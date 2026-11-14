import { describe, expect, it } from "vitest";
import { STEPS, stepReached } from "./steps";
import { initialUi, type Ui } from "./voice/store";

const at = (over: Partial<Ui>) => stepReached({ ...initialUi, ...over });
const turn = { id: "t1", role: "user" as const, text: "maitoa", final: true };
const done = { fi: "", en: "" };

describe("stepper: Need -> Basket -> Quote -> Confirm -> Approval", () => {
  it("names the five steps", () => {
    expect(STEPS).toEqual(["Need", "Basket", "Quote", "Confirm", "Approval"]);
  });
  it("starts before the first step, and a conversation or options are the need", () => {
    expect(at({})).toBe(-1);
    expect(at({ turns: [turn] })).toBe(0);
    expect(at({ offerSetId: "OS-1" })).toBe(0);
  });
  it("a basket in focus is the basket step", () => {
    expect(at({ basketId: "B-0A1B2C3D4E", offerSetId: "OS-1" })).toBe(1);
  });
  it("a quote is the quote step until the agent asks to confirm that quote", () => {
    expect(at({ basketId: "B-0A1B2C3D4E", quoteId: "Q-1" })).toBe(2);
    expect(at({ quoteId: "Q-1", confirmQuoteId: "Q-1" })).toBe(3);
    expect(at({ quoteId: "Q-2", confirmQuoteId: "Q-1" })).toBe(2);
  });
  it("an approval is the last step; an order within the cap finishes every step", () => {
    expect(at({ quoteId: "Q-1", approvalId: "A-1" })).toBe(4);
    expect(at({ quoteId: "Q-1", order: { quoteId: "Q-1", orderId: "O-1", status: "completed", message: done } })).toBe(5);
    expect(at({ quoteId: "Q-1", lastOutcome: { tool: "place_order", status: "completed", reasonCode: null, at: 1 } })).toBe(5);
    expect(at({ quoteId: "Q-1", order: { quoteId: "Q-0", orderId: "O-0", status: "completed", message: done } })).toBe(2);
  });
  it("a new basket after an approval starts again at the basket step", () => {
    expect(at({ basketId: "B-0A1B2C3D4E", approvalId: "A-1" })).toBe(1);
  });
});
