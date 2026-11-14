/**
 * The mix, rendered once when the page loads with OfflineAudioContext, in 3-second pieces at once (each piece
 * holds only the cues that start in it and lasts until they ring out). Music, effects and voices render as
 * separate tracks. Every voice line is levelled (its loudest 20 ms at −10 dB) and starts at its first word; the
 * music dips to 40 % under it. A soft limiter keeps the sum under 0.95. The same buffer plays in the preview
 * and goes into the MP4.
 */
import { CARD_BEATS, BEAT, SEGMENTS, TOTAL } from "../timeline.js";
import { mulberry } from "../kit/rand.js";
import { score } from "./score.js";
import { SOUNDS, soundLength } from "./synth.js";

const SR = 48000;
const PIECE = 3;
const LEVELS = { music: 0.5, sfx: 0.85, voice: 1.0 };
const DUCK = 0.4;

/** Title cards: the slam, the typing, a riser into the drop. */
function cardCues() {
  const drop = CARD_BEATS * BEAT;
  return [
    { at: 0, sound: "cardHit", gain: 0.75 },
    { at: 0.2, sound: "typing", dur: 0.45, gain: 0.7 },
    { at: drop - 0.28, sound: "riser", dur: 0.28, gain: 0.5 },
  ];
}

async function fetchBuffer(url, decoder) {
  const res = await fetch(url);
  if (!res.ok) return null;
  return decoder.decodeAudioData(await res.arrayBuffer());
}

/** Speech start and end (20 ms RMS windows) and the gain that puts the loudest window at −10 dB. */
export function analyseVoice(buffer) {
  const win = Math.round(buffer.sampleRate * 0.02);
  const ch = [...Array(buffer.numberOfChannels).keys()].map((c) => buffer.getChannelData(c));
  const rms = [];
  for (let i = 0; i + win <= buffer.length; i += win) {
    let s = 0;
    for (let k = i; k < i + win; k++) {
      let v = 0;
      for (const c of ch) v += c[k];
      v /= ch.length;
      s += v * v;
    }
    rms.push(Math.sqrt(s / win));
  }
  const peak = Math.max(...rms, 1e-6);
  const thr = Math.max(peak * 0.1, 0.004);
  const first = rms.findIndex((r) => r > thr);
  let last = rms.length - 1;
  while (last > 0 && rms[last] <= thr) last--;
  return { start: Math.max(0, first * 0.02 - 0.02), end: (last + 1) * 0.02, gain: 0.316 / peak, length: buffer.duration };
}

function impulse(ctx, seconds, seed) {
  const len = Math.round(ctx.sampleRate * seconds);
  const b = ctx.createBuffer(2, len, ctx.sampleRate);
  const r = mulberry(seed);
  for (let c = 0; c < 2; c++) {
    const d = b.getChannelData(c);
    for (let i = 0; i < len; i++) d[i] = (r() * 2 - 1) * Math.pow(1 - i / len, 3);
  }
  return b;
}

async function renderPieces(cues, play) {
  const total = Math.ceil(TOTAL * SR);
  const out = [new Float32Array(total), new Float32Array(total)];
  const n = Math.ceil(TOTAL / PIECE);
  await Promise.all(
    Array.from({ length: n }, async (_, k) => {
      const t0 = k * PIECE;
      const mine = cues.filter((c) => c.T >= t0 && c.T < t0 + PIECE);
      if (!mine.length) return;
      const len = Math.max(PIECE, ...mine.map((c) => c.T - t0 + c.len)) + 0.1;
      const ctx = new OfflineAudioContext(2, Math.ceil(len * SR), SR);
      const bus = ctx.createGain();
      bus.connect(ctx.destination);
      for (const c of mine) play(ctx, bus, c.T - t0, c);
      const buf = await ctx.startRendering();
      const off = Math.round(t0 * SR);
      for (let c = 0; c < 2; c++) {
        const src = buf.getChannelData(c);
        const dst = out[c];
        const m = Math.min(src.length, total - off);
        for (let i = 0; i < m; i++) dst[off + i] += src[i];
      }
    }),
  );
  return out;
}

export async function buildMix(modules) {
  const decoder = new OfflineAudioContext(1, 1, SR);
  const music = [];
  const sfx = [];
  const voices = [];
  for (const seg of SEGMENTS) {
    const list = modules.get(seg.view)?.sounds?.(seg) ?? [];
    const all = [...(seg.card ? cardCues() : []), ...list];
    for (const c of all) {
      if (c.music) for (const m of score(c, seg)) music.push({ ...m, T: seg.start + m.at, seg });
      else if (c.voice) voices.push({ ...c, T: seg.start + c.at, seg });
      else if (c.sound || c.moo) sfx.push({ ...c, T: seg.start + c.at, seg });
    }
  }

  // assets: moos and voices
  const mooBuffers = new Map();
  const mooCount = new Map();
  for (const c of sfx.filter((x) => x.moo)) {
    const n = (mooCount.get(c.moo) ?? 0) + 1;
    mooCount.set(c.moo, n);
    const file = `${c.moo}-${c.moo === "chewing" ? 1 : ((n - 1) % 2) + 1}`;
    if (!mooBuffers.has(file)) mooBuffers.set(file, await fetchBuffer(`/moo/${file}.mp3`, decoder));
    c.buffer = mooBuffers.get(file);
    c.level = c.buffer ? analyseVoice(c.buffer) : null;
  }
  const available = new Set(await (await fetch("/voices")).json());
  const voiceStats = [];
  for (const v of voices) {
    v.buffer = available.has(v.voice) ? await fetchBuffer(`/audio/voice/${v.voice}.mp3`, decoder) : null;
    if (!v.buffer) {
      voiceStats.push({ name: v.voice, missing: true });
      continue;
    }
    v.level = analyseVoice(v.buffer);
    const rate = v.rate ?? 1;
    v.speech = (v.level.end - v.level.start) / rate;
    if (v.cut) v.speech = Math.min(v.speech, v.cut);
    v.len = (v.buffer.duration - v.level.start) / rate + (v.room ? 2.5 : 0.1);
    const endsAt = v.at + v.speech;
    voiceStats.push({
      name: v.voice,
      segment: v.seg.id,
      at: v.at,
      speech: +v.speech.toFixed(2),
      endsAt: +endsAt.toFixed(2),
      segmentEnd: +v.seg.duration.toFixed(2),
      overrun: endsAt > v.seg.duration ? +(endsAt - v.seg.duration).toFixed(2) : 0,
      leadIn: +v.level.start.toFixed(2),
    });
  }

  for (const c of music) c.len = soundLength(c);
  for (const c of sfx) c.len = c.moo ? (c.buffer ? c.buffer.duration / (c.rate ?? 1) + 0.05 : 0) : soundLength(c);

  const playSound = (ctx, out, t, c) => {
    if (c.moo) {
      if (!c.buffer) return;
      const s = ctx.createBufferSource();
      s.buffer = c.buffer;
      s.playbackRate.value = c.rate ?? 1;
      const g = ctx.createGain();
      g.gain.value = (c.gain ?? 1) * Math.min(4, c.level.gain * 0.6);
      s.connect(g).connect(out);
      s.start(t);
      return;
    }
    SOUNDS[c.sound].play(ctx, out, t, { ...c, seed: Math.round(c.T * 1000) });
  };
  const [musicL, musicR] = await renderPieces(music, playSound);
  const [sfxL, sfxR] = await renderPieces(sfx, playSound);

  // voices: one context, few nodes
  const total = Math.ceil(TOTAL * SR);
  const vctx = new OfflineAudioContext(2, total, SR);
  const rooms = {};
  const roomBus = (name) => {
    if (!rooms[name]) {
      const conv = vctx.createConvolver();
      conv.buffer = impulse(vctx, name === "valley" ? 3.5 : 2.2, name);
      const wet = vctx.createGain();
      wet.gain.value = name === "valley" ? 0.5 : 0.3;
      conv.connect(wet).connect(vctx.destination);
      rooms[name] = conv;
    }
    return rooms[name];
  };
  for (const v of voices) {
    if (!v.buffer) continue;
    const s = vctx.createBufferSource();
    s.buffer = v.buffer;
    s.playbackRate.value = v.rate ?? 1;
    const g = vctx.createGain();
    g.gain.value = (v.gain ?? 1) * v.level.gain;
    let head = s;
    if (v.fx === "robot") {
      // ring modulation plus a little dry signal, then a band-limited, crunchy tone
      const ring = vctx.createGain();
      ring.gain.value = 0;
      const lfo = vctx.createOscillator();
      lfo.frequency.value = 62;
      lfo.connect(ring.gain);
      lfo.start(v.T);
      lfo.stop(v.T + v.len);
      const dry = vctx.createGain();
      dry.gain.value = 0.35;
      const sum = vctx.createGain();
      s.connect(ring).connect(sum);
      s.connect(dry).connect(sum);
      const hp = vctx.createBiquadFilter();
      hp.type = "highpass";
      hp.frequency.value = 350;
      const crush = vctx.createWaveShaper();
      const curve = new Float32Array(256);
      for (let i = 0; i < 256; i++) curve[i] = Math.round(((i / 255) * 2 - 1) * 12) / 12;
      crush.curve = curve;
      sum.connect(hp).connect(crush);
      head = crush;
    }
    head.connect(g).connect(vctx.destination);
    if (v.room) g.connect(roomBus(v.room));
    s.start(v.T, v.level.start);
    if (v.cut) {
      // cut off mid-word (the robot, by the stamp)
      g.gain.setValueAtTime(g.gain.value, v.T + v.cut - 0.02);
      g.gain.linearRampToValueAtTime(0, v.T + v.cut + 0.02);
      s.stop(v.T + v.cut + 0.05);
    }
  }
  const vbuf = await vctx.startRendering();
  const voiceL = vbuf.getChannelData(0);
  const voiceR = vbuf.getChannelData(1);

  // duck the music under the voices: 40 % while a line is spoken
  const duck = new Float32Array(total).fill(1);
  for (const v of voices) {
    if (!v.buffer) continue;
    const a = Math.max(0, Math.round((v.T - 0.06) * SR));
    const b = Math.min(total, Math.round((v.T + v.speech + 0.2) * SR));
    for (let i = a; i < b; i++) {
      const rampIn = Math.min(1, (i - a) / (0.06 * SR));
      const rampOut = Math.min(1, (b - i) / (0.2 * SR));
      duck[i] = Math.min(duck[i], 1 - (1 - DUCK) * Math.min(rampIn, rampOut));
    }
  }

  const buffer = new AudioBuffer({ length: total, numberOfChannels: 2, sampleRate: SR });
  const L = buffer.getChannelData(0);
  const R = buffer.getChannelData(1);
  let peak = 0;
  let rawPeak = 0;
  for (let i = 0; i < total; i++) {
    const l = musicL[i] * LEVELS.music * duck[i] + sfxL[i] * LEVELS.sfx + voiceL[i] * LEVELS.voice;
    const r = musicR[i] * LEVELS.music * duck[i] + sfxR[i] * LEVELS.sfx + voiceR[i] * LEVELS.voice;
    rawPeak = Math.max(rawPeak, Math.abs(l), Math.abs(r));
    L[i] = limit(l);
    R[i] = limit(r);
    peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
  }
  return {
    buffer,
    peak,
    voices: voiceStats,
    stats: { rawPeak: +rawPeak.toFixed(3), peak: +peak.toFixed(3), cues: { music: music.length, sfx: sfx.length, voices: voices.length }, voices: voiceStats },
  };
}

/** Soft limiter: linear to 0.8, then a tanh knee that never passes 0.95. */
function limit(x) {
  const a = Math.abs(x);
  if (a <= 0.8) return x;
  return Math.sign(x) * (0.8 + 0.15 * Math.tanh((a - 0.8) / 0.15));
}
