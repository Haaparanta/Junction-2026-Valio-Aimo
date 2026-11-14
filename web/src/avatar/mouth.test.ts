import { describe, expect, it } from "vitest";
import { bands, energy, follow, gain, hysteresis, shapeFor } from "./mouth";

const spectrum = (fill: (hz: number) => number) =>
  Uint8Array.from({ length: 1024 }, (_, i) => fill(100 + 7.7 * i));

describe("mouth driver", () => {
  it("silence keeps the mouth closed", () => {
    const b = bands(new Uint8Array(1024));
    expect(energy(b)).toBe(0);
    expect(shapeFor(b, 0)).toBe("M");
    expect(bands([])).toEqual({ low: 0, mid: 0, high: 0 });
  });
  it("low-band energy opens the mouth more than high-band energy", () => {
    const low = bands(spectrum((hz) => (hz < 900 ? 200 : 0)));
    const high = bands(spectrum((hz) => (hz > 2500 ? 200 : 0)));
    expect(energy(low)).toBeGreaterThan(energy(high));
    expect(shapeFor(high, 0.5)).toBe("F");
    expect(shapeFor(low, 0.3)).toBe("O");
    expect(shapeFor(bands(spectrum((hz) => (hz > 900 && hz < 2500 ? 200 : 40))), 0.5)).toBe("E");
  });
  it("attack is faster than release", () => {
    const up = follow(0, 1, 16);
    const down = 1 - follow(1, 0, 16);
    expect(up).toBeGreaterThan(down);
  });
  it("auto-gain normalises to the recent peak", () => {
    const g = gain(0.2, 0.1, 16);
    expect(g.level).toBeCloseTo(0.5, 1);
    expect(gain(0.2, 0.5, 16).level).toBe(1);
  });
  it("hysteresis needs three frames", () => {
    let s = { shape: "M" as const as "M" | "A" | "E" | "O" | "F", candidate: "M" as "M" | "A" | "E" | "O" | "F", count: 0 };
    s = hysteresis(s, "A");
    s = hysteresis(s, "A");
    expect(s.shape).toBe("M");
    s = hysteresis(s, "A");
    expect(s.shape).toBe("A");
  });
});
