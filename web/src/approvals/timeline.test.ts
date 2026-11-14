import { describe, expect, it } from "vitest";
import { actionLabel, channelLabel, shortHash, timelineRows, when } from "./timeline";

describe("timeline view model", () => {
  const ev = (seq: number, extra: object = {}) => ({
    seq, at: `2026-11-14T08:0${seq}:00+02:00`, actor: "buyer-91c2", channel: "voice", action: "place_order",
    decision: "requires_escalation", hash: `sha256:abcdef0123456789${seq}`, prev_hash: "sha256:0000000000000000", ...extra,
  });
  it("sorts by seq and labels channel and action", () => {
    const rows = timelineRows([ev(2, { channel: "console", action: "decide_approval" }), ev(1)]);
    expect(rows.map((r) => r.seq)).toEqual([1, 2]);
    expect(rows[0]).toMatchObject({ channel: "Voice", action: "Order requested", hash: "abcdef0123" });
    expect(rows[1]).toMatchObject({ channel: "Approver console", action: "Approval decided" });
  });
  it("detail {fi,en}, plain detail or a summary becomes the text", () => {
    const rows = timelineRows([
      ev(1, { detail: { fi: "Hyväksytty", en: "Approved" } }), ev(2, { detail: "Plain" }), ev(3, { summary: "Sum" }), ev(4),
    ]);
    expect(rows.map((r) => r.text)).toEqual(["Approved", "Plain", "Sum", ""]);
  });
  it("unknown labels are made readable", () => {
    expect(actionLabel("export_ubl")).toBe("Export ubl");
    expect(channelLabel("a2a")).toBe("A2a");
    expect(shortHash("12345")).toBe("12345");
    expect(when("not a time")).toBe("not a time");
  });
});
