import { describe, expect, it } from "vitest";
import { moodFromTool, outcomeFromTool } from "./mood";

const r = (o: unknown) => ({ is_error: false, full_tool_result: JSON.stringify(o) });

describe("moodFromTool (gateway status, never LLM text)", () => {
  it("is alarmed on requires_escalation, canceled, any reason_code, errors and blocks", () => {
    expect(moodFromTool(r({ status: "requires_escalation", reason_code: "limit_exceeded" }))).toBe("alarmed");
    expect(moodFromTool(r({ status: "canceled" }))).toBe("alarmed");
    expect(moodFromTool(r({ status: "incomplete", reason_code: "confirmation_required" }))).toBe("alarmed");
    expect(moodFromTool({ is_error: true })).toBe("alarmed");
    expect(moodFromTool({ is_error: false, is_blocked: true })).toBe("alarmed");
  });
  it("celebrates completed", () => {
    expect(moodFromTool(r({ status: "completed", reason_code: null }))).toBe("celebrate");
  });
  it("stays neutral on ok, truncated or non-JSON payloads", () => {
    expect(moodFromTool(r({ status: "ok", reason_code: null }))).toBeNull();
    expect(moodFromTool({ is_error: false, truncated: true, full_tool_result: "{" })).toBeNull();
    expect(moodFromTool({ is_error: false, full_tool_result: "not json" })).toBeNull();
    expect(moodFromTool({ is_error: false })).toBeNull();
  });
  it("ignores status words inside LLM-ish text fields", () => {
    expect(moodFromTool(r({ status: "ok", message_for_user: { en: "requires_escalation completed" } }))).toBeNull();
  });
});

describe("outcomeFromTool", () => {
  it("reads status and reason_code", () => {
    expect(outcomeFromTool(r({ status: "requires_escalation", reason_code: "limit_exceeded" })))
      .toEqual({ status: "requires_escalation", reasonCode: "limit_exceeded" });
    expect(outcomeFromTool(r({ status: "ok" }))).toEqual({ status: "ok", reasonCode: null });
    expect(outcomeFromTool({ is_error: true })).toEqual({ status: "error", reasonCode: "tool_error" });
  });
});
