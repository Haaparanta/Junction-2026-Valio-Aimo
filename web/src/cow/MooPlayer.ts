/**
 * Mansikki's moos: recorded ElevenLabs SFX v3 clips from public/sfx/moo (scripts/gen_moos.py), normalised on
 * decode, with a Web Audio synthesis as the fallback while they load or if they fail. Two channels: one-shot
 * moos and the chewing loop. Everything goes through one analyser that drives the cow's mouth.
 */
import type { Mood } from "./mood";

/**
 * A cow's moo, roughly: a nasal "mmm" (mouth closed, energy below 300 Hz) that opens into a long "ooo"/"aw"
 * (formants near 450-700 Hz and 1,000-1,300 Hz), voiced at 100-200 Hz with a rough, breathy source, the pitch
 * rising into the call and sagging at the end. f0 points are spread evenly over the call.
 */
type Contour = { f0: number[]; dur: number; open: number; loud: number; count?: number };

export const CONTOURS: Record<Mood, Contour> = {
  greet: { f0: [105, 140, 150, 120, 95], dur: 2.0, open: 1, loud: 0.8 },
  happy: { f0: [120, 155, 135], dur: 0.95, open: 0.9, loud: 0.7, count: 2 },
  question: { f0: [110, 120, 125, 175], dur: 1.5, open: 0.9, loud: 0.75 },
  alarmed: { f0: [170, 215, 205, 140], dur: 1.3, open: 1.1, loud: 1 },
  celebrate: { f0: [125, 165, 190, 185, 150], dur: 2.1, open: 1.1, loud: 0.9 },
};

/** Schedules one moo on any (also offline) audio context; returns its end time and sources. */
export function scheduleMoo(ctx: BaseAudioContext, out: AudioNode, t0: number, c: Contour) {
  const t1 = t0 + c.dur;
  const tOpen = t0 + Math.min(0.35, c.dur * 0.22); // "mmm" -> "ooo"
  const tClose = t1 - Math.min(0.4, c.dur * 0.25);
  const sources: AudioScheduledSourceNode[] = [];

  // Source: two slightly detuned saws, a subharmonic for roughness, and breath noise.
  const pitch = ctx.createConstantSource();
  const step = c.dur / (c.f0.length - 1);
  pitch.offset.setValueAtTime(c.f0[0] ?? 120, t0);
  c.f0.forEach((f, i) => i > 0 && pitch.offset.linearRampToValueAtTime(f, t0 + i * step));
  const wobble = ctx.createOscillator(); // slow, uneven vibrato
  wobble.frequency.value = 4.3;
  const wobbleDepth = ctx.createGain();
  wobbleDepth.gain.value = 2.5;
  wobble.connect(wobbleDepth);
  const voice = ctx.createGain();
  voice.gain.value = 0.5;
  for (const [type, ratio, detune, level] of [
    ["sawtooth", 1, -6, 0.6], ["sawtooth", 1, 7, 0.5], ["square", 0.5, 0, 0.04],
  ] as const) {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.value = 0;
    o.detune.value = detune;
    const scale = ctx.createGain();
    scale.gain.value = ratio;
    pitch.connect(scale).connect(o.frequency);
    wobbleDepth.connect(o.frequency);
    const g = ctx.createGain();
    g.gain.value = level;
    o.connect(g).connect(voice);
    sources.push(o);
  }
  const noiseBuf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * (c.dur + 0.1)), ctx.sampleRate);
  const nd = noiseBuf.getChannelData(0);
  for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;
  const noise = ctx.createBufferSource();
  noise.buffer = noiseBuf;
  const breath = ctx.createBiquadFilter();
  breath.type = "bandpass";
  breath.frequency.value = 1400;
  breath.Q.value = 0.7;
  const breathGain = ctx.createGain();
  breathGain.gain.value = 0.05;
  noise.connect(breath).connect(breathGain).connect(voice);
  sources.push(noise, pitch, wobble);

  // Vocal tract: nasal low-pass that opens, plus two moving formants in parallel.
  const tract = ctx.createGain();
  const nasal = ctx.createBiquadFilter();
  nasal.type = "lowpass";
  nasal.Q.value = 0.8;
  nasal.frequency.setValueAtTime(320, t0);
  nasal.frequency.linearRampToValueAtTime(1800 * c.open, tOpen + 0.15);
  nasal.frequency.setValueAtTime(1800 * c.open, tClose);
  nasal.frequency.linearRampToValueAtTime(380, t1);
  voice.connect(nasal);
  for (const [f, q, g] of [[[300, 650, 480], 4, 1.0], [[900, 1200, 950], 6, 0.55]] as const) {
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.Q.value = q;
    bp.frequency.setValueAtTime(f[0], t0);
    bp.frequency.linearRampToValueAtTime(f[1] * c.open, tOpen + 0.2);
    bp.frequency.setValueAtTime(f[1] * c.open, tClose);
    bp.frequency.linearRampToValueAtTime(f[2], t1);
    const bg = ctx.createGain();
    bg.gain.value = g * 2.2;
    nasal.connect(bp).connect(bg).connect(tract);
  }
  const body = ctx.createGain(); // keep some of the full nasal sound under the formants
  body.gain.value = 0.35;
  nasal.connect(body).connect(tract);

  // Envelope: soft "mmm" onset, full voice once open, a sagging fade.
  const env = ctx.createGain();
  env.gain.setValueAtTime(0.0001, t0);
  env.gain.exponentialRampToValueAtTime(0.35 * c.loud, t0 + 0.12);
  env.gain.linearRampToValueAtTime(0.9 * c.loud, tOpen + 0.1);
  env.gain.setValueAtTime(0.85 * c.loud, tClose);
  env.gain.exponentialRampToValueAtTime(0.0001, t1);
  tract.connect(env).connect(out);

  for (const s of sources) {
    s.start(t0);
    s.stop(t1 + 0.05);
  }
  return { end: t1, sources };
}

export class MooPlayer {
  private ctx: AudioContext | null = null;
  private out: GainNode | null = null;
  readonly analyser: AnalyserNode | null = null;
  private loop: { stop: () => void } | null = null;
  private playing = new Set<AudioScheduledSourceNode>();
  private clips: Partial<Record<Mood | "chewing", { buffer: AudioBuffer; gain: number }[]>> = {};
  private lastTake: Partial<Record<Mood, number>> = {};

  /** Call inside a click handler: browsers only start audio after a user gesture. */
  unlock(): void {
    if (!this.ctx) {
      const ctx = new AudioContext();
      const out = ctx.createGain();
      out.gain.value = 0.5;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      out.connect(analyser).connect(ctx.destination);
      this.ctx = ctx;
      this.out = out;
      (this as { analyser: AnalyserNode | null }).analyser = analyser;
      void this.load(ctx); // not awaited: never block the Start click on downloads
    }
    void this.ctx.resume();
  }

  private async load(ctx: AudioContext): Promise<void> {
    try {
      const manifest = (await (await fetch("/sfx/moo/manifest.json")).json()) as Record<string, string[]>;
      await Promise.all(Object.entries(manifest).map(async ([mood, files]) => {
        const takes = await Promise.all(files.map(async (f) => {
          const buffer = await ctx.decodeAudioData(await (await fetch(f)).arrayBuffer());
          return { buffer, gain: normalisingGain(buffer, mood === "chewing" ? 0.03 : 0.09) };
        }));
        this.clips[mood as Mood | "chewing"] = takes;
      }));
    } catch {
      /* keep the synthesized fallback */
    }
  }

  /** Plays a recorded take (never the same one twice in a row); resolves when it ends. */
  private playClip(ctx: AudioContext, out: AudioNode, mood: Mood): Promise<void> | null {
    const takes = this.clips[mood];
    if (!takes?.length) return null;
    let i = Math.floor(Math.random() * takes.length);
    if (takes.length > 1 && i === this.lastTake[mood]) i = (i + 1) % takes.length;
    this.lastTake[mood] = i;
    const take = takes[i];
    if (!take) return null;
    const src = ctx.createBufferSource();
    src.buffer = take.buffer;
    const g = ctx.createGain();
    g.gain.value = take.gain;
    src.connect(g).connect(out);
    this.playing.add(src);
    return new Promise((resolve) => {
      // onended never fires while the context is suspended: a timer guarantees the turn loop moves on.
      const timer = setTimeout(done, (take.buffer.duration + 0.5) * 1000);
      function done() {
        clearTimeout(timer);
        resolve();
      }
      src.onended = () => {
        this.playing.delete(src);
        done();
      };
      src.start();
    });
  }

  get ready(): boolean {
    return this.ctx !== null;
  }

  /** One mood; resolves when the moo has finished. */
  play(mood: Mood): Promise<void> {
    const { ctx, out } = this;
    if (!ctx || !out) return Promise.resolve();
    const recorded = this.playClip(ctx, out, mood);
    if (recorded) return recorded;
    const c = CONTOURS[mood];
    const count = c.count ?? 1;
    let t = ctx.currentTime + 0.02;
    let end = t;
    for (let i = 0; i < count; i++) {
      end = this.moo(ctx, out, t, c);
      t = end + 0.18;
    }
    return new Promise((resolve) => setTimeout(resolve, (end - ctx.currentTime) * 1000));
  }

  private moo(ctx: AudioContext, out: AudioNode, t0: number, c: Contour): number {
    const { end, sources } = scheduleMoo(ctx, out, t0, c);
    for (const s of sources) {
      this.playing.add(s);
      s.onended = () => this.playing.delete(s);
    }
    return end;
  }

  stopOneShot(): void {
    this.playing.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    });
    this.playing.clear();
  }

  /** Soft chewing while a gateway tool runs. */
  startLoop(): void {
    const { ctx, out } = this;
    if (!ctx || !out || this.loop) return;
    const chew = this.clips.chewing?.[0];
    if (chew) {
      const src = ctx.createBufferSource();
      src.buffer = chew.buffer;
      src.loop = true;
      const g = ctx.createGain();
      g.gain.value = chew.gain;
      src.connect(g).connect(out);
      src.start();
      this.loop = { stop: () => { try { src.stop(); } catch { /* stopped */ } } };
      return;
    }
    const len = ctx.sampleRate * 2;
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) {
      const phase = (i / ctx.sampleRate) % 0.42; // a chew every 0.42 s
      const burst = phase < 0.09 ? Math.sin((phase / 0.09) * Math.PI) : 0;
      d[i] = (Math.random() * 2 - 1) * burst * 0.35;
    }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = 900;
    const g = ctx.createGain();
    g.gain.value = 0.5;
    src.connect(bp).connect(g).connect(out);
    src.start();
    this.loop = {
      stop: () => {
        try {
          src.stop();
        } catch {
          /* stopped */
        }
      },
    };
  }

  stopLoop(): void {
    this.loop?.stop();
    this.loop = null;
  }
}

/** Gain that brings a clip's loud part to the target RMS, capped so near-silent clips are not blown up. */
export function normalisingGain(buffer: { getChannelData(c: number): Float32Array; length: number }, target: number): number {
  const d = buffer.getChannelData(0);
  let peak = 0;
  let sum = 0;
  let n = 0;
  for (let i = 0; i < d.length; i++) {
    const x = Math.abs(d[i] ?? 0);
    peak = Math.max(peak, x);
    if (x > 0.005) {
      sum += x * x;
      n++;
    }
  }
  if (n === 0 || peak === 0) return 1;
  const rms = Math.sqrt(sum / n);
  return Math.min(target / rms, 0.95 / peak, 8);
}

export const mooPlayer = new MooPlayer();
