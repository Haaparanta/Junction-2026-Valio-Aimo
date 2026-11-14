/**
 * The sound kit: every instrument and effect is made from oscillators, filters and seeded noise, never sampled.
 * SOUNDS[name] = { len(o) → seconds, play(ctx, out, t, o) }. o: { gain = 1, freq, dur, seed }.
 * Mansikki's moos are the app's own clips (web/public/sfx/moo), played by the mix.
 */
import { mulberry } from "../kit/rand.js";

const noiseCache = new WeakMap();
function noiseBuffer(ctx) {
  if (!noiseCache.has(ctx)) {
    const len = ctx.sampleRate * 2;
    const b = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = b.getChannelData(0);
    const r = mulberry("noise");
    for (let i = 0; i < len; i++) d[i] = r() * 2 - 1;
    noiseCache.set(ctx, b);
  }
  return noiseCache.get(ctx);
}

function noise(ctx, t, dur, offset = 0) {
  const s = ctx.createBufferSource();
  s.buffer = noiseBuffer(ctx);
  s.loop = true;
  s.start(t, (offset * 0.37) % 1.9);
  s.stop(t + dur + 0.05);
  return s;
}

function osc(ctx, type, freq, t, dur) {
  const o = ctx.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(freq, t);
  o.start(t);
  o.stop(t + dur + 0.05);
  return o;
}

function filt(ctx, type, freq, Q = 0.7) {
  const f = ctx.createBiquadFilter();
  f.type = type;
  f.frequency.value = freq;
  f.Q.value = Q;
  return f;
}

/** A gain stage with an attack/hold/decay envelope, connected to out. */
function vca(ctx, out, t, { a = 0.004, hold = 0, d = 0.3, peak = 1 } = {}) {
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), t + a);
  if (hold > 0) g.gain.setValueAtTime(Math.max(0.0002, peak), t + a + hold);
  g.gain.exponentialRampToValueAtTime(0.0001, t + a + hold + d);
  g.connect(out);
  return g;
}

function shaper(ctx, amount = 2) {
  const s = ctx.createWaveShaper();
  const n = 1024;
  const c = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    c[i] = Math.tanh(amount * x) / Math.tanh(amount);
  }
  s.curve = c;
  return s;
}

const chain = (...nodes) => {
  for (let i = 0; i < nodes.length - 1; i++) nodes[i].connect(nodes[i + 1]);
  return nodes[nodes.length - 1];
};

const midi = (m) => 440 * 2 ** ((m - 69) / 12);
export { midi };

export const SOUNDS = {
  // ---------- drums and instruments ----------
  kick: {
    len: () => 0.45,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sine", 160, t, 0.45);
      o.frequency.exponentialRampToValueAtTime(42, t + 0.12);
      chain(o, vca(ctx, out, t, { d: 0.4, peak: gain }));
      chain(noise(ctx, t, 0.02, t), filt(ctx, "highpass", 3000), vca(ctx, out, t, { d: 0.02, peak: 0.3 * gain }));
    },
  },
  clap: {
    len: () => 0.3,
    play(ctx, out, t, { gain = 1 }) {
      const bp = filt(ctx, "bandpass", 1400, 0.9);
      bp.connect(out);
      for (const [dt, p] of [[0, 0.8], [0.012, 0.7], [0.024, 1]]) chain(noise(ctx, t + dt, 0.25, t + dt), vca(ctx, bp, t + dt, { d: dt === 0.024 ? 0.2 : 0.012, peak: p * gain * 1.6 }));
    },
  },
  snare: {
    len: () => 0.3,
    play(ctx, out, t, { gain = 1 }) {
      chain(noise(ctx, t, 0.25, t), filt(ctx, "bandpass", 1900, 0.8), vca(ctx, out, t, { d: 0.18, peak: gain }));
      chain(osc(ctx, "triangle", 190, t, 0.15), vca(ctx, out, t, { d: 0.1, peak: 0.5 * gain }));
    },
  },
  hat: {
    len: (o) => (o.open ? 0.35 : 0.08),
    play(ctx, out, t, { gain = 1, open = false }) {
      chain(noise(ctx, t, open ? 0.35 : 0.08, t), filt(ctx, "highpass", 7500), vca(ctx, out, t, { d: open ? 0.28 : 0.045, peak: 0.5 * gain }));
    },
  },
  bass808: {
    len: (o) => (o.dur ?? 0.6) + 0.1,
    play(ctx, out, t, { gain = 1, freq = 55, dur = 0.6, grit = 1.6 }) {
      const o = osc(ctx, "sine", freq * 1.06, t, dur + 0.1);
      o.frequency.exponentialRampToValueAtTime(freq, t + 0.06);
      chain(o, shaper(ctx, grit), filt(ctx, "lowpass", 900), vca(ctx, out, t, { a: 0.004, hold: dur * 0.5, d: dur * 0.5, peak: 0.9 * gain }));
    },
  },
  cowbell: {
    len: () => 0.35,
    play(ctx, out, t, { gain = 1, freq = 800 }) {
      const bp = filt(ctx, "bandpass", freq, 1.2);
      const g = vca(ctx, out, t, { d: 0.28, peak: 0.6 * gain });
      bp.connect(g);
      osc(ctx, "square", freq * 0.675, t, 0.35).connect(bp);
      osc(ctx, "square", freq, t, 0.35).connect(bp);
    },
  },
  pad: {
    len: (o) => (o.dur ?? 2) + 0.6,
    play(ctx, out, t, { gain = 1, notes = [57, 60, 64], dur = 2 }) {
      const lp = filt(ctx, "lowpass", 1100);
      chain(lp, vca(ctx, out, t, { a: 0.25, hold: dur, d: 0.5, peak: 0.12 * gain }));
      for (const m of notes) for (const det of [-6, 6]) {
        const o = osc(ctx, "sawtooth", midi(m), t, dur + 0.8);
        o.detune.value = det;
        o.connect(lp);
      }
    },
  },
  musicBox: {
    len: () => 1.3,
    play(ctx, out, t, { gain = 1, freq = 880 }) {
      for (const [h, p, d] of [[1, 1, 1.2], [2, 0.3, 0.6], [3, 0.12, 0.3]]) chain(osc(ctx, "sine", freq * h, t, d), vca(ctx, out, t, { a: 0.002, d, peak: 0.25 * p * gain }));
    },
  },
  pluck: {
    len: () => 0.5,
    play(ctx, out, t, { gain = 1, freq = 440 }) {
      const lp = filt(ctx, "lowpass", 2400);
      lp.frequency.exponentialRampToValueAtTime(400, t + 0.3);
      chain(osc(ctx, "sawtooth", freq, t, 0.5), lp, vca(ctx, out, t, { d: 0.4, peak: 0.25 * gain }));
    },
  },
  stab: {
    len: () => 0.5,
    play(ctx, out, t, { gain = 1, notes = [57, 60, 64] }) {
      const lp = filt(ctx, "lowpass", 2600);
      chain(lp, vca(ctx, out, t, { a: 0.01, d: 0.4, peak: 0.18 * gain }));
      for (const m of notes) for (const det of [-10, 10]) {
        const o = osc(ctx, "sawtooth", midi(m), t, 0.5);
        o.detune.value = det;
        o.connect(lp);
      }
    },
  },
  violin: {
    len: (o) => (o.dur ?? 0.6) + 0.3,
    play(ctx, out, t, { gain = 1, freq = 440, dur = 0.6 }) {
      const o = osc(ctx, "sawtooth", freq, t, dur + 0.3);
      const lfo = osc(ctx, "sine", 5.5, t, dur + 0.3);
      const depth = ctx.createGain();
      depth.gain.value = freq * 0.008;
      chain(lfo, depth, o.frequency);
      chain(o, filt(ctx, "bandpass", 1600, 0.7), filt(ctx, "lowpass", 3500), vca(ctx, out, t, { a: 0.08, hold: dur, d: 0.2, peak: 0.3 * gain }));
    },
  },

  // ---------- effects ----------
  boom: {
    len: () => 1.4,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sine", 75, t, 1.4);
      o.frequency.exponentialRampToValueAtTime(32, t + 0.9);
      chain(o, shaper(ctx, 1.5), vca(ctx, out, t, { d: 1.3, peak: gain }));
      chain(noise(ctx, t, 0.4, t), filt(ctx, "lowpass", 500), vca(ctx, out, t, { d: 0.35, peak: 0.6 * gain }));
    },
  },
  slam: {
    len: () => 0.8,
    play(ctx, out, t, o) {
      SOUNDS.kick.play(ctx, out, t, { gain: o.gain ?? 1 });
      chain(noise(ctx, t, 0.6, t), filt(ctx, "lowpass", 1200), vca(ctx, out, t, { d: 0.5, peak: 0.7 * (o.gain ?? 1) }));
    },
  },
  cardHit: {
    len: () => 1.4,
    play(ctx, out, t, { gain = 1 }) {
      SOUNDS.boom.play(ctx, out, t, { gain: 0.8 * gain });
      chain(noise(ctx, t, 0.15, t), filt(ctx, "highpass", 2500), vca(ctx, out, t, { d: 0.12, peak: 0.4 * gain }));
    },
  },
  typing: {
    len: (o) => (o.dur ?? 0.4) + 0.05,
    play(ctx, out, t, { gain = 1, dur = 0.4, seed = 1 }) {
      const r = mulberry(seed + 99);
      for (let x = 0; x < dur; x += 0.035 + r() * 0.02) chain(noise(ctx, t + x, 0.02, x * 7), filt(ctx, "bandpass", 3000 + r() * 1500, 2), vca(ctx, out, t + x, { d: 0.015, peak: 0.35 * gain }));
    },
  },
  whoosh: {
    len: (o) => (o.dur ?? 0.45) + 0.1,
    play(ctx, out, t, { gain = 1, dur = 0.45 }) {
      const bp = filt(ctx, "bandpass", 300, 1.2);
      bp.frequency.setValueAtTime(300, t);
      bp.frequency.exponentialRampToValueAtTime(3200, t + dur * 0.6);
      bp.frequency.exponentialRampToValueAtTime(600, t + dur);
      chain(noise(ctx, t, dur, t), bp, vca(ctx, out, t, { a: dur * 0.5, d: dur * 0.5, peak: 0.9 * gain }));
    },
  },
  riser: {
    len: (o) => (o.dur ?? 0.3) + 0.05,
    play(ctx, out, t, { gain = 1, dur = 0.3 }) {
      const hp = filt(ctx, "bandpass", 500, 1.5);
      hp.frequency.exponentialRampToValueAtTime(6000, t + dur);
      chain(noise(ctx, t, dur, t), hp, vca(ctx, out, t, { a: dur * 0.9, d: 0.05, peak: 0.6 * gain }));
    },
  },
  confetti: {
    len: () => 1.0,
    play(ctx, out, t, { gain = 1 }) {
      chain(noise(ctx, t, 0.05, t), filt(ctx, "highpass", 1500), vca(ctx, out, t, { d: 0.05, peak: gain }));
      chain(noise(ctx, t + 0.03, 0.9, t + 1), filt(ctx, "bandpass", 5000, 1.5), vca(ctx, out, t + 0.03, { a: 0.05, d: 0.8, peak: 0.25 * gain }));
    },
  },
  poof: {
    len: () => 0.5,
    play(ctx, out, t, { gain = 1 }) {
      const lp = filt(ctx, "lowpass", 1800);
      lp.frequency.exponentialRampToValueAtTime(300, t + 0.35);
      chain(noise(ctx, t, 0.4, t), lp, vca(ctx, out, t, { a: 0.01, d: 0.35, peak: gain }));
    },
  },
  twinkle: {
    len: () => 0.9,
    play(ctx, out, t, { gain = 1 }) {
      [2093, 2637, 3136, 4186].forEach((f, i) => chain(osc(ctx, "sine", f, t + i * 0.06, 0.5), vca(ctx, out, t + i * 0.06, { d: 0.45, peak: 0.18 * gain })));
    },
  },
  sparkle: { len: () => 0.9, play: (ctx, out, t, o) => SOUNDS.twinkle.play(ctx, out, t, o) },
  ding: {
    len: () => 1.2,
    play(ctx, out, t, { gain = 1 }) {
      chain(osc(ctx, "sine", 1319, t, 1.2), vca(ctx, out, t, { d: 1.1, peak: 0.35 * gain }));
      chain(osc(ctx, "sine", 2637, t, 0.6), vca(ctx, out, t, { d: 0.5, peak: 0.12 * gain }));
    },
  },
  zoom: {
    len: () => 0.3,
    play(ctx, out, t, { gain = 1 }) {
      const bp = filt(ctx, "bandpass", 600, 2);
      bp.frequency.exponentialRampToValueAtTime(5000, t + 0.2);
      chain(noise(ctx, t, 0.25, t), bp, vca(ctx, out, t, { a: 0.15, d: 0.08, peak: 0.6 * gain }));
    },
  },
  hum: {
    len: (o) => (o.dur ?? 3) + 0.2,
    play(ctx, out, t, { gain = 1, dur = 3 }) {
      const g = vca(ctx, out, t, { a: 0.2, hold: dur - 0.4, d: 0.2, peak: 0.12 * gain });
      osc(ctx, "sine", 55, t, dur).connect(g);
      chain(osc(ctx, "triangle", 110, t, dur), filt(ctx, "lowpass", 300), g);
    },
  },
  paper: {
    len: () => 0.5,
    play(ctx, out, t, { gain = 1 }) {
      const r = mulberry(17);
      for (let x = 0; x < 0.4; x += 0.04) chain(noise(ctx, t + x, 0.05, x * 3), filt(ctx, "bandpass", 2500 + r() * 2500, 1.5), vca(ctx, out, t + x, { d: 0.04, peak: (0.2 + r() * 0.3) * gain }));
    },
  },
  shutter: {
    len: () => 0.3,
    play(ctx, out, t, { gain = 1 }) {
      for (const dt of [0, 0.07]) chain(noise(ctx, t + dt, 0.03, dt), filt(ctx, "highpass", 2000), vca(ctx, out, t + dt, { d: 0.03, peak: gain }));
      chain(osc(ctx, "square", 1200, t + 0.02, 0.05), filt(ctx, "lowpass", 3000), vca(ctx, out, t + 0.02, { d: 0.04, peak: 0.1 * gain }));
    },
  },
  pop: {
    len: () => 0.15,
    play(ctx, out, t, { gain = 1, freq = 600 }) {
      const o = osc(ctx, "sine", freq, t, 0.12);
      o.frequency.exponentialRampToValueAtTime(freq * 2.2, t + 0.06);
      chain(o, vca(ctx, out, t, { a: 0.002, d: 0.09, peak: 0.45 * gain }));
    },
  },
  error: {
    len: () => 0.35,
    play(ctx, out, t, { gain = 1 }) {
      for (const dt of [0, 0.15]) chain(osc(ctx, "square", 196, t + dt, 0.12), filt(ctx, "lowpass", 1400), vca(ctx, out, t + dt, { a: 0.005, hold: 0.08, d: 0.03, peak: 0.25 * gain }));
    },
  },
  sadTrombone: {
    len: () => 1.9,
    play(ctx, out, t, { gain = 1 }) {
      const notes = [[62, 0, 0.28], [61, 0.32, 0.28], [60, 0.64, 0.28], [59, 0.96, 0.85]];
      for (const [m, dt, d] of notes) {
        const o = osc(ctx, "sawtooth", midi(m - 12), t + dt, d + 0.1);
        if (d > 0.5) {
          const lfo = osc(ctx, "sine", 6, t + dt, d);
          const dep = ctx.createGain();
          dep.gain.value = 3;
          chain(lfo, dep, o.frequency);
        }
        const lp = filt(ctx, "lowpass", 900, 2);
        chain(o, lp, vca(ctx, out, t + dt, { a: 0.03, hold: d - 0.08, d: 0.08, peak: 0.25 * gain }));
      }
    },
  },
  cheer: {
    len: () => 1.6,
    play(ctx, out, t, { gain = 1 }) {
      for (const [f, p] of [[600, 0.6], [1300, 0.5], [2600, 0.3]]) chain(noise(ctx, t, 1.5, f), filt(ctx, "bandpass", f, 1.5), vca(ctx, out, t, { a: 0.15, hold: 0.5, d: 0.8, peak: p * gain }));
      for (let i = 0; i < 4; i++) {
        const o = osc(ctx, "triangle", 320 + i * 60, t + i * 0.08, 0.5);
        o.frequency.exponentialRampToValueAtTime(700 + i * 80, t + i * 0.08 + 0.35);
        chain(o, vca(ctx, out, t + i * 0.08, { a: 0.05, d: 0.4, peak: 0.06 * gain }));
      }
    },
  },
  beep: {
    len: () => 0.15,
    play(ctx, out, t, { gain = 1, freq = 988 }) {
      chain(osc(ctx, "square", freq, t, 0.1), filt(ctx, "lowpass", 2500), vca(ctx, out, t, { a: 0.003, hold: 0.06, d: 0.02, peak: 0.18 * gain }));
    },
  },
  rattle: {
    len: () => 0.8,
    play(ctx, out, t, { gain = 1 }) {
      const r = mulberry(5);
      for (let i = 0; i < 14; i++) {
        const dt = r() * 0.6;
        chain(noise(ctx, t + dt, 0.04, i), filt(ctx, "bandpass", 900 + r() * 2500, 3), vca(ctx, out, t + dt, { d: 0.05, peak: (0.3 + r() * 0.5) * gain }));
      }
    },
  },
  record: {
    len: () => 0.4,
    play(ctx, out, t, { gain = 1 }) {
      const bp = filt(ctx, "bandpass", 2500, 4);
      bp.frequency.exponentialRampToValueAtTime(250, t + 0.25);
      chain(noise(ctx, t, 0.3, t), bp, vca(ctx, out, t, { a: 0.01, d: 0.25, peak: 1.2 * gain }));
    },
  },
  thud: {
    len: () => 0.4,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sine", 110, t, 0.3);
      o.frequency.exponentialRampToValueAtTime(48, t + 0.15);
      chain(o, vca(ctx, out, t, { d: 0.25, peak: gain }));
      chain(noise(ctx, t, 0.1, t), filt(ctx, "lowpass", 600), vca(ctx, out, t, { d: 0.08, peak: 0.5 * gain }));
    },
  },
  zap: {
    len: () => 0.4,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sawtooth", 1500, t, 0.3);
      o.frequency.exponentialRampToValueAtTime(120, t + 0.25);
      chain(o, filt(ctx, "lowpass", 3000), vca(ctx, out, t, { d: 0.25, peak: 0.3 * gain }));
      chain(noise(ctx, t, 0.3, t), filt(ctx, "highpass", 4000), vca(ctx, out, t, { d: 0.25, peak: 0.4 * gain }));
    },
  },
  crash: {
    len: () => 0.9,
    play(ctx, out, t, { gain = 1 }) {
      chain(noise(ctx, t, 0.8, t), filt(ctx, "lowpass", 3500), vca(ctx, out, t, { d: 0.7, peak: 0.7 * gain }));
      for (const f of [310, 455, 690]) chain(osc(ctx, "square", f, t, 0.5), filt(ctx, "bandpass", f * 2, 4), vca(ctx, out, t, { d: 0.4, peak: 0.08 * gain }));
      SOUNDS.thud.play(ctx, out, t, { gain: 0.8 * gain });
    },
  },
  tick: {
    len: (o) => (o.dur ?? 0.5) + 0.05,
    play(ctx, out, t, { gain = 1, dur = 0.5 }) {
      for (let x = 0; x < dur; x += 0.11) chain(noise(ctx, t + x, 0.01, x), filt(ctx, "bandpass", 4000, 3), vca(ctx, out, t + x, { d: 0.012, peak: 0.6 * gain }));
    },
  },
  bonk: {
    len: () => 0.35,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sine", 420, t, 0.2);
      o.frequency.exponentialRampToValueAtTime(160, t + 0.12);
      chain(o, vca(ctx, out, t, { d: 0.18, peak: 0.8 * gain }));
      chain(osc(ctx, "sine", 900, t, 0.08), vca(ctx, out, t, { d: 0.06, peak: 0.4 * gain }));
    },
  },
  kaching: {
    len: () => 1.3,
    play(ctx, out, t, { gain = 1 }) {
      chain(noise(ctx, t, 0.08, t), filt(ctx, "bandpass", 3000, 2), vca(ctx, out, t, { d: 0.06, peak: 0.5 * gain }));
      for (const [f, dt] of [[2093, 0.08], [3136, 0.08], [2637, 0.2], [4186, 0.2]]) chain(osc(ctx, "sine", f, t + dt, 1), vca(ctx, out, t + dt, { d: 0.9, peak: 0.12 * gain }));
      SOUNDS.thud.play(ctx, out, t, { gain: 0.4 * gain });
    },
  },
  notify: {
    len: () => 0.4,
    play(ctx, out, t, { gain = 1 }) {
      for (const [f, dt] of [[880, 0], [1319, 0.11]]) chain(osc(ctx, "sine", f, t + dt, 0.25), vca(ctx, out, t + dt, { d: 0.22, peak: 0.3 * gain }));
    },
  },
  click: {
    len: () => 0.1,
    play(ctx, out, t, { gain = 1 }) {
      chain(noise(ctx, t, 0.02, t), filt(ctx, "bandpass", 2500, 2), vca(ctx, out, t, { d: 0.02, peak: gain }));
    },
  },
  stampLime: {
    len: () => 0.5,
    play(ctx, out, t, { gain = 1 }) {
      SOUNDS.thud.play(ctx, out, t, { gain });
      chain(noise(ctx, t, 0.06, t), filt(ctx, "highpass", 1500), vca(ctx, out, t, { d: 0.05, peak: 0.6 * gain }));
    },
  },
  steam: {
    len: (o) => (o.dur ?? 2) + 0.2,
    play(ctx, out, t, { gain = 1, dur = 2 }) {
      chain(noise(ctx, t, dur, t), filt(ctx, "highpass", 2500), vca(ctx, out, t, { a: 0.3, hold: dur - 0.6, d: 0.3, peak: 0.25 * gain }));
    },
  },
  loyly: {
    len: () => 1.6,
    play(ctx, out, t, { gain = 1 }) {
      chain(noise(ctx, t, 1.5, t), filt(ctx, "bandpass", 3500, 0.8), vca(ctx, out, t, { a: 0.03, d: 1.4, peak: 0.9 * gain }));
      chain(noise(ctx, t, 0.8, t + 3), filt(ctx, "lowpass", 500), vca(ctx, out, t, { a: 0.02, d: 0.7, peak: 0.4 * gain }));
    },
  },
  vinylStop: {
    len: () => 0.5,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sawtooth", 330, t, 0.45);
      o.frequency.exponentialRampToValueAtTime(30, t + 0.4);
      chain(o, filt(ctx, "lowpass", 1200), vca(ctx, out, t, { a: 0.005, hold: 0.25, d: 0.15, peak: 0.25 * gain }));
    },
  },
  sonicBoom: {
    len: () => 2.2,
    play(ctx, out, t, { gain = 1 }) {
      SOUNDS.boom.play(ctx, out, t, { gain });
      chain(noise(ctx, t, 0.08, t), filt(ctx, "highpass", 800), vca(ctx, out, t, { d: 0.08, peak: 0.8 * gain }));
      chain(noise(ctx, t, 2, t + 2), filt(ctx, "lowpass", 220), vca(ctx, out, t, { a: 0.05, d: 1.9, peak: 0.8 * gain }));
    },
  },
  launch: {
    len: () => 1.1,
    play(ctx, out, t, { gain = 1 }) {
      const bp = filt(ctx, "bandpass", 400, 1.5);
      bp.frequency.exponentialRampToValueAtTime(6000, t + 0.8);
      chain(noise(ctx, t, 1, t), bp, vca(ctx, out, t, { a: 0.1, d: 0.85, peak: 0.8 * gain }));
      const o = osc(ctx, "sine", 500, t, 1);
      o.frequency.exponentialRampToValueAtTime(2200, t + 0.8);
      chain(o, vca(ctx, out, t, { a: 0.05, d: 0.85, peak: 0.18 * gain }));
    },
  },
  printer: {
    len: () => 0.6,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "square", 140, t, 0.45);
      const am = osc(ctx, "square", 32, t, 0.45);
      const g = ctx.createGain();
      g.gain.value = 0.5;
      am.connect(g.gain);
      chain(o, g, filt(ctx, "bandpass", 1200, 1), vca(ctx, out, t, { a: 0.01, hold: 0.35, d: 0.05, peak: 0.25 * gain }));
      SOUNDS.click.play(ctx, out, t + 0.45, { gain: 0.6 * gain });
    },
  },
  servo: {
    len: () => 0.4,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sawtooth", 220, t, 0.35);
      o.frequency.linearRampToValueAtTime(420, t + 0.3);
      chain(o, filt(ctx, "lowpass", 900), vca(ctx, out, t, { a: 0.02, hold: 0.22, d: 0.08, peak: 0.15 * gain }));
    },
  },
  powerDown: {
    len: () => 0.8,
    play(ctx, out, t, { gain = 1 }) {
      const o = osc(ctx, "sine", 900, t, 0.7);
      o.frequency.exponentialRampToValueAtTime(70, t + 0.6);
      chain(o, vca(ctx, out, t, { a: 0.01, hold: 0.4, d: 0.2, peak: 0.25 * gain }));
    },
  },
  chain: {
    len: () => 0.3,
    play(ctx, out, t, { gain = 1, seed = 0 }) {
      const k = 1 + (seed % 3) * 0.06;
      for (const f of [2400, 3700]) chain(osc(ctx, "sine", f * k, t, 0.2), vca(ctx, out, t, { d: 0.18, peak: 0.12 * gain }));
    },
  },
  swirl: {
    len: () => 2.4,
    play(ctx, out, t, { gain = 1 }) {
      const bp = filt(ctx, "bandpass", 300, 2);
      bp.frequency.exponentialRampToValueAtTime(2500, t + 1.4);
      bp.frequency.exponentialRampToValueAtTime(800, t + 2.2);
      chain(noise(ctx, t, 2.3, t), bp, vca(ctx, out, t, { a: 0.8, d: 1.4, peak: 0.6 * gain }));
      SOUNDS.twinkle.play(ctx, out, t + 1.3, { gain: 0.6 * gain });
    },
  },
  drone: {
    len: (o) => (o.dur ?? 3) + 0.4,
    play(ctx, out, t, { gain = 1, dur = 3 }) {
      const g = vca(ctx, out, t, { a: 0.6, hold: dur - 1, d: 0.6, peak: 0.2 * gain });
      osc(ctx, "sine", 55, t, dur).connect(g);
      osc(ctx, "sine", 82.4, t, dur).connect(g);
      const s = osc(ctx, "sawtooth", 110, t, dur);
      s.detune.value = 7;
      chain(s, filt(ctx, "lowpass", 280), g);
    },
  },
};

/** Length in seconds of a sound cue (for planning the mix pieces). */
export function soundLength(cue) {
  const s = SOUNDS[cue.sound];
  if (!s) throw new Error(`unknown sound ${cue.sound}`);
  return s.len(cue);
}
