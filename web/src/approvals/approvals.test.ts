import { describe, expect, it } from "vitest";
import type { Approval, Me } from "../api";
import {
  approvalIdFromPath, approvalNote, approverLabel, buyerOutcome, cleanComment, decisionMessage, isFinal, isPending,
  screenFor,
} from "./approvals";

describe("approverLabel", () => {
  it("names the generic approver role as the buyer's manager", () => {
    expect(approverLabel("approver")).toBe("your manager");
    expect(approverLabel("head_chef")).toBe("head chef");
  });
});

const me = (role: string): Me => ({
  buyer_id: "x", display_name: "X", org_id: "kitchen-42", role, order_cap_eur: "500.00", as_of: "2026-11-14T08:00:00+02:00",
});

function answer(status: string, reason_code: string | null, comment = ""): Approval {
  return {
    status, reason_code, warnings: [], message_for_user: { fi: "fi", en: "Gateway says so." }, approval_id: "AP-1",
    approval: {
      approval_id: "AP-1", status, order_id: "O-1", quote_id: "Q-1", reasons: [], decide_by: "", approver_role: "approver",
      comment,
    },
  };
}

describe("role routing", () => {
  it("approver role gets the console, any other role the buyer workspace", () => {
    expect(screenFor(undefined)).toBe("loading");
    expect(screenFor(null)).toBe("login");
    expect(screenFor(me("approver"))).toBe("approver");
    expect(screenFor(me("buyer"))).toBe("buyer");
    expect(screenFor(me(""))).toBe("buyer");
  });
});

describe("decision messages", () => {
  it("approve that completes the order", () => {
    const m = decisionMessage("approve", answer("completed", null));
    expect(m.tone).toBe("ok");
    expect(m.title).toBe("Approved. Order O-1 is placed.");
    expect(m.detail).toBe(""); // the gateway's sentence would only repeat the title
  });
  it("reject cancels with approval_rejected", () => {
    const m = decisionMessage("reject", answer("canceled", "approval_rejected"));
    expect(m.tone).toBe("bad");
    expect(m.title).toMatch(/^Rejected\. Order O-1 is canceled/);
    expect(m.detail).toBe("");
  });
  it("price_changed keeps the order waiting and asks for a new quote", () => {
    const m = decisionMessage("approve", answer("requires_escalation", "price_changed"));
    expect(m.tone).toBe("warn");
    expect(m.title).toMatch(/new quote/);
  });
  it("quote_expired says it is too late, whatever the status", () => {
    expect(decisionMessage("approve", answer("canceled", "quote_expired")).title).toMatch(/^Too late/);
  });
  it("a second decision answers the first one unchanged: say the earlier decision stands", () => {
    expect(decisionMessage("approve", answer("canceled", "approval_rejected")).title).toBe(
      "Already rejected earlier. Your earlier decision stands.",
    );
    expect(decisionMessage("reject", answer("completed", null)).title).toMatch(/^Already approved earlier/);
  });
});

describe("buyer outcome", () => {
  it("completed, rejected with the comment, expired", () => {
    expect(buyerOutcome(answer("completed", null)).title).toBe("Approved: order O-1 is placed.");
    const r = buyerOutcome(answer("canceled", "approval_rejected", "  Too much butter.  "));
    expect(r).toMatchObject({ tone: "bad", title: "Rejected by the approver.", comment: "Too much butter." });
    expect(buyerOutcome(answer("canceled", "quote_expired")).title).toMatch(/expired/);
  });
  it("a missing comment is empty", () => {
    const a = answer("completed", null);
    delete a.approval.comment;
    expect(buyerOutcome(a).comment).toBe("");
  });
});

describe("agent note, path and comment", () => {
  it("the note carries ids, status and reason, never prices", () => {
    expect(approvalNote(answer("canceled", "approval_rejected"))).toBe(
      "Order O-1 status changed to canceled, reason approval_rejected (approval AP-1).",
    );
    expect(approvalNote(answer("completed", null))).toBe("Order O-1 status changed to completed (approval AP-1).");
  });
  it("status helpers", () => {
    expect(isPending("requires_escalation")).toBe(true);
    expect(isFinal("completed") && isFinal("canceled") && !isFinal("requires_escalation")).toBe(true);
  });
  it("only a clean /approvals/{id} path gives an id", () => {
    expect(approvalIdFromPath("/approvals/AP-1A2B3C")).toBe("AP-1A2B3C");
    expect(approvalIdFromPath("/approvals/AP-1A2B3C/")).toBe("AP-1A2B3C");
    expect(approvalIdFromPath("/approvals/../x")).toBe("");
    expect(approvalIdFromPath("/")).toBe("");
  });
  it("comments are trimmed and capped", () => {
    expect(cleanComment("  ok  ")).toBe("ok");
    expect(cleanComment("x".repeat(600))).toHaveLength(500);
  });
});
