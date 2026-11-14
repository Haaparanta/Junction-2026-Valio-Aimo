/** The order progress shown above the cards, read from the store only (never from LLM text). */
import type { Ui } from "./voice/store";

export const STEPS = ["Need", "Basket", "Quote", "Confirm", "Approval"] as const;

export type StepInput = Pick<
  Ui, "turns" | "offerSetId" | "basketId" | "quoteId" | "confirmQuoteId" | "approvalId" | "order" | "lastOutcome"
>;

/**
 * The step reached: -1 before anything happened, 0..4 for STEPS, and STEPS.length once the order went through
 * without needing an approval (every step done). Options on screen are still part of the need.
 */
export function stepReached(s: StepInput): number {
  if (s.quoteId) {
    if (s.approvalId) return 4;
    const placedHere = s.order?.quoteId === s.quoteId && s.order.status === "completed";
    const placedByAgent = s.lastOutcome?.tool === "place_order" && s.lastOutcome.status === "completed";
    if (placedHere || placedByAgent) return STEPS.length;
    return s.confirmQuoteId === s.quoteId ? 3 : 2;
  }
  if (s.basketId) return 1;
  return s.offerSetId || s.turns.length ? 0 : -1;
}
