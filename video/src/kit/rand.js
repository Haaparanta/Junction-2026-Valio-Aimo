/** Seeded random numbers and smooth noise: every frame and every sound can be made again exactly. */

export function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32: a fast 32-bit generator. */
export function mulberry(seed) {
  let a = (typeof seed === "string" ? hash(seed) : seed) >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function rng(seed) {
  const next = mulberry(seed);
  return {
    next,
    float: (a = 0, b = 1) => a + (b - a) * next(),
    int: (a, b) => Math.floor(a + (b - a + 1) * next()),
    pick: (list) => list[Math.floor(next() * list.length)],
    sign: () => (next() < 0.5 ? -1 : 1),
  };
}

/** Value noise in [-1, 1], smooth in x; the same x and seed always give the same value. */
export function noise1(x, seed = 0) {
  const i = Math.floor(x);
  const f = x - i;
  const a = lattice(i, seed);
  const b = lattice(i + 1, seed);
  const u = f * f * (3 - 2 * f);
  return a + (b - a) * u;
}

function lattice(i, seed) {
  let h = Math.imul(i ^ Math.imul(seed + 1, 0x27d4eb2d), 0x165667b1);
  h ^= h >>> 15;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  return ((h >>> 0) / 4294967295) * 2 - 1;
}
