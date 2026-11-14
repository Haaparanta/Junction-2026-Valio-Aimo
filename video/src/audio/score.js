/**
 * An original 140 BPM beat in A minor (A–F–C–G), one style per scene. Each scene's beat starts on its drop
 * (`from`, the end of its title card), so every cut lands on the grid. In rest windows only the hi-hats and
 * the pad play, for the big moments.
 *
 * Styles: hype (the hook), lofi (3 AM), trap, phonk (cowbell riff, the gym bro), eerie (space, the end).
 */
import { BEAT } from "../timeline.js";
import { midi } from "./synth.js";

const STEP = BEAT / 4;
const ROOTS = [33, 29, 36, 31]; // A1 F1 C2 G1
const CHORDS = [[57, 60, 64], [53, 57, 60], [55, 60, 64], [55, 59, 62]];
const PHONK_BELL = [[0, 81], [2, 79], [3, 81], [6, 76], [8, 81], [10, 79], [11, 81], [14, 84]];
const MELODY = [[0, 2], [3, 1], [6, 0], [10, 2], [12, 1]];

const STYLES = {
  hype: { kick: [0, 4, 8, 12], clap: [4, 12], hats: 1, bass: [0, 8], stab: [0, 10], gain: 1 },
  trap: { kick: [0, 7, 10], clap: [4, 12], hats: 2, rolls: true, bass: [0, 7, 10], pluck: true, pad: 0.6, gain: 0.9 },
  lofi: { kick: [0, 9], snare: [4, 12], hats: 2, swing: 0.03, bass: [0], pad: 1, box: true, gain: 0.75 },
  phonk: { kick: [0, 6, 10], clap: [4, 12], hats: 2, bass: [0, 6, 10], grit: 3.5, bell: true, gain: 1 },
  eerie: { pad: 1.2, box: true, slow: true, gain: 0.8 },
};

/** Music cues (local times) for one segment: spec = { music, from, rests }. */
export function score(spec, segment) {
  const st = STYLES[spec.music];
  if (!st) return [];
  const rests = spec.rests ?? [];
  const resting = (t) => rests.some(([a, b]) => t >= a && t < b);
  const cues = [];
  const end = segment.duration - 0.04;
  const add = (at, sound, o = {}) => {
    if (at < end) cues.push({ at, sound, ...o, gain: (o.gain ?? 1) * st.gain });
  };
  for (let bar = 0; ; bar++) {
    const t0 = spec.from + bar * 16 * STEP;
    if (t0 >= end) break;
    const ci = bar % 4;
    if (st.pad) add(t0, "pad", { notes: CHORDS[ci], dur: (st.slow ? 32 : 16) * STEP, gain: st.pad });
    if (st.slow && bar % 2 === 1) continue;
    for (let s = 0; s < 16; s++) {
      const t = t0 + s * STEP;
      if (t >= end) break;
      const rest = resting(t);
      // hats keep going in the rests, quieter
      if (st.hats && s % st.hats === 0) add(t + (st.swing && s % 4 === 2 ? st.swing : 0), "hat", { gain: rest ? 0.35 : 0.55 });
      if (st.rolls && !rest && bar % 2 === 1 && s >= 13) add(t + STEP / 2, "hat", { gain: 0.4 });
      if (rest) continue;
      if (st.kick?.includes(s)) add(t, "kick", { gain: 0.95 });
      if (st.clap?.includes(s)) add(t, "clap", { gain: 0.7 });
      if (st.snare?.includes(s)) add(t, "snare", { gain: 0.45 });
      if (st.bass?.includes(s)) {
        const next = st.bass.find((x) => x > s) ?? 16;
        add(t, "bass808", { freq: midi(ROOTS[ci]), dur: (next - s) * STEP * 0.95, grit: st.grit ?? 1.6, gain: 0.85 });
      }
      if (st.stab?.includes(s)) add(t, "stab", { notes: CHORDS[ci].map((m) => m + 12), gain: 0.9 });
      if (st.bell) for (const [bs, m] of PHONK_BELL) if (bs === s) add(t, "cowbell", { freq: midi(m - 12) * 1.0, gain: 0.55 });
      if (st.pluck && bar % 2 === 0) for (const [ms, k] of MELODY) if (ms === s) add(t, "pluck", { freq: midi(CHORDS[ci][k] + 12), gain: 0.55 });
      if (st.box && (s === 0 || s === 6 || s === 10)) add(t, "musicBox", { freq: midi(CHORDS[ci][(s / 2) % 3] + 24), gain: st.slow ? 0.8 : 0.5 });
    }
  }
  return cues;
}
