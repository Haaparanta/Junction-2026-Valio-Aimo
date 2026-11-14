/**
 * Mouth driver maths (tech-research §5): output frequency bands -> openness and a mouth shape.
 * getOutputByteFrequencyData() gives 1024 bins over 100-8000 Hz, bin i ≈ 100 + 7.7·i Hz.
 */
export type MouthShape = "M" | "A" | "E" | "O" | "F";
export type Bands = { low: number; mid: number; high: number };

const binOf = (hz: number, n: number) => Math.max(0, Math.min(n - 1, Math.round(((hz - 100) / 7900) * n)));

function mean(data: ArrayLike<number>, from: number, to: number): number {
  let s = 0;
  for (let i = from; i <= to; i++) s += data[i] ?? 0;
  return to >= from ? s / (to - from + 1) / 255 : 0;
}

export function bands(data: ArrayLike<number>): Bands {
  const n = data.length;
  if (n === 0) return { low: 0, mid: 0, high: 0 };
  return {
    low: mean(data, binOf(150, n), binOf(900, n)),
    mid: mean(data, binOf(900, n), binOf(2500, n)),
    high: mean(data, binOf(2500, n), binOf(8000, n)),
  };
}

export const energy = (b: Bands) => 0.6 * b.low + 0.3 * b.mid + 0.1 * b.high;

/** Auto-gain: a decaying peak, so quiet and loud voices both open the mouth fully. */
export function gain(peak: number, e: number, dtMs: number): { peak: number; level: number } {
  const decayed = Math.max(0.05, peak * Math.exp(-dtMs / 1500));
  const p = Math.max(decayed, e);
  return { peak: p, level: Math.min(1, e / p) };
}

/** Fast attack (40 ms), slower release (90 ms). */
export function follow(prev: number, target: number, dtMs: number): number {
  const tau = target > prev ? 40 : 90;
  return prev + (target - prev) * (1 - Math.exp(-dtMs / tau));
}

export function shapeFor(b: Bands, open: number): MouthShape {
  if (open < 0.12) return "M";
  const total = b.low + b.mid + b.high || 1;
  if (b.high / total > 0.38) return "F";
  if (b.mid / total > 0.42) return "E";
  if (b.low / total > 0.62 && open < 0.55) return "O";
  return "A";
}

/** Change shape only after it has been stable for 3 frames. */
export function hysteresis(state: { shape: MouthShape; candidate: MouthShape; count: number }, next: MouthShape) {
  if (next === state.shape) return { ...state, candidate: next, count: 0 };
  const count = next === state.candidate ? state.count + 1 : 1;
  return count >= 3 ? { shape: next, candidate: next, count: 0 } : { ...state, candidate: next, count };
}
