import { describe, expect, it } from "vitest";
import { initialUi } from "../voice/store";
import { avatarState, expression, THINKING_WATCHDOG_MS } from "./state";

const live = { ...initialUi, phase: "live" as const };

describe("avatar state", () => {
  it("follows the call lifecycle", () => {
    expect(avatarState(initialUi, 0)).toBe("idle");
    expect(avatarState({ ...initialUi, phase: "connecting" }, 0)).toBe("connecting");
    expect(avatarState({ ...initialUi, phase: "error" }, 0)).toBe("error");
    expect(avatarState({ ...live, queue: "waiting" }, 0)).toBe("queued");
    expect(avatarState(live, 0)).toBe("listening");
    expect(avatarState({ ...live, userSpeaking: true }, 0)).toBe("userSpeaking");
    expect(avatarState({ ...live, mode: "speaking" }, 0)).toBe("speaking");
  });
  it("thinks only while a gateway tool is in flight, with a watchdog", () => {
    const pending = { t1: { tool: "get_offers", since: 1000 } };
    expect(avatarState({ ...live, pendingTools: pending }, 2000)).toBe("thinking");
    expect(avatarState({ ...live, pendingTools: pending }, 1000 + THINKING_WATCHDOG_MS + 1)).toBe("listening");
  });
  it("expressions come from gateway status", () => {
    expect(expression({ tool: "place_order", status: "requires_escalation", reasonCode: "limit_exceeded", at: 0 }, 1)).toBe("concerned");
    expect(expression({ tool: "get_order", status: "completed", reasonCode: null, at: 0 }, 1)).toBe("happy");
    expect(expression({ tool: "get_offers", status: "ok", reasonCode: null, at: 0 }, 1)).toBe("neutral");
    expect(expression({ tool: "get_order", status: "completed", reasonCode: null, at: 0 }, 70_000)).toBe("neutral");
    expect(expression(null, 0)).toBe("neutral");
  });
});
