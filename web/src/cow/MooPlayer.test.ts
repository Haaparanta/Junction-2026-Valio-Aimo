import { describe, expect, it } from "vitest";
import { normalisingGain } from "./MooPlayer";

const clip = (amp: number) => ({ length: 1000, getChannelData: () => Float32Array.from({ length: 1000 }, (_, i) => amp * Math.sin(i / 5)) });

describe("normalisingGain", () => {
  it("brings quiet and loud clips to a similar level", () => {
    const quiet = normalisingGain(clip(0.08), 0.09) * 0.08;
    const loud = normalisingGain(clip(0.6), 0.09) * 0.6;
    expect(Math.abs(quiet - loud)).toBeLessThan(0.01);
  });
  it("never clips and never boosts silence wildly", () => {
    const loud = clip(0.9);
    const peak = Math.max(...Array.from(loud.getChannelData(), Math.abs));
    expect(normalisingGain(loud, 2) * peak).toBeLessThanOrEqual(0.95 + 1e-9);
    expect(normalisingGain(clip(0.001), 0.09)).toBe(1);
  });
});
