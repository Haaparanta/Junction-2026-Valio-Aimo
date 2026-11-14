/** Easing, keyframe tracks and slow motion. Views set every value from t with these. */

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, k) => a + (b - a) * k;
/** 0 before a, 1 after b, linear between. */
export const seg = (t, a, b) => clamp((t - a) / (b - a));

export const E = {
  linear: (x) => x,
  inQuad: (x) => x * x,
  outQuad: (x) => 1 - (1 - x) * (1 - x),
  inOutQuad: (x) => (x < 0.5 ? 2 * x * x : 1 - (-2 * x + 2) ** 2 / 2),
  inCubic: (x) => x * x * x,
  outCubic: (x) => 1 - (1 - x) ** 3,
  inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2),
  outQuart: (x) => 1 - (1 - x) ** 4,
  inExpo: (x) => (x === 0 ? 0 : 2 ** (10 * x - 10)),
  outExpo: (x) => (x === 1 ? 1 : 1 - 2 ** (-10 * x)),
  outBack: (x) => 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2,
  inBack: (x) => 2.70158 * x * x * x - 1.70158 * x * x,
  outElastic: (x) =>
    x === 0 || x === 1 ? x : 2 ** (-10 * x) * Math.sin(((x * 10 - 0.75) * 2 * Math.PI) / 3) + 1,
  outBounce: (x) => {
    const n = 7.5625;
    const d = 2.75;
    if (x < 1 / d) return n * x * x;
    if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75;
    if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375;
    return n * (x -= 2.625 / d) * x + 0.984375;
  },
  step: (x) => (x < 1 ? 0 : 1),
};

/** Eased 0..1 between a and b. */
export const ease = (t, a, b, name = "inOutCubic") => E[name](seg(t, a, b));

/**
 * A keyframe track: [[t, value, easeIntoThisKey?], …]. Values are numbers or arrays of numbers.
 * Before the first key it holds the first value, after the last it holds the last.
 */
export function track(keys) {
  return (t) => {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const [t1, v1, e = "inOutCubic"] = keys[i];
      if (t <= t1) {
        const [t0, v0] = keys[i - 1];
        const k = E[e](seg(t, t0, t1));
        return Array.isArray(v0) ? v0.map((x, j) => lerp(x, v1[j], k)) : lerp(v0, v1, k);
      }
    }
    return keys[keys.length - 1][1];
  };
}

/**
 * Slow motion: maps the real local time to action time. windows = [[from, to, speed]] in real time,
 * with speed < 1 inside. Outside the windows action time runs at 1.
 */
export function timewarp(windows) {
  return (t) => {
    let a = 0;
    let last = 0;
    for (const [from, to, speed] of windows) {
      if (t <= from) break;
      a += from - last;
      const inside = Math.min(t, to) - from;
      a += inside * speed;
      last = Math.min(t, to);
      if (t <= to) return a;
    }
    return a + (t - last);
  };
}

/** A pop-in scale: 0 before at, overshoots, settles at 1. */
export const pop = (t, at, dur = 0.35) => (t < at ? 0 : E.outBack(seg(t, at, at + dur)));
/** 0 → 1 → 0 bump between a and b. */
export const bump = (t, a, b) => Math.sin(Math.PI * seg(t, a, b));
/** Fades in over fin after a, out over fout before b. */
export const window01 = (t, a, b, fin = 0.15, fout = 0.15) => Math.min(seg(t, a, a + fin), 1 - seg(t, b - fout, b));
/** Characters of text shown by t when typing at cps characters a second from at. */
export const typed = (text, t, at, cps = 28) => {
  const chars = [...text];
  return chars.slice(0, Math.max(0, Math.floor((t - at) * cps))).join("");
};
