/**
 * Placeholder moos synthesized with Web Audio: no ElevenLabs credits are spent. Recorded SFX v3 moos replace
 * these once approved (PLAN M17.1, scripts/gen_moos.py). Two channels: one-shot moos and the chewing loop.
 */
import type { Mood } from "./mood";

type Contour = { f0: number[]; dur: number; formant: number; count?: number };

const CONTOURS: Record<Mood, Contour> = {
  greet: { f0: [95, 125, 110, 85], dur: 1.4, formant: 650 },
  happy: { f0: [110, 135, 120], dur: 0.6, formant: 750, count: 2 },
  question: { f0: [95, 100, 150], dur: 1.1, formant: 700 },
  alarmed: { f0: [190, 210, 120], dur: 0.9, formant: 900 },
  celebrate: { f0: [120, 160, 190, 170], dur: 1.2, formant: 850 },
};

export class MooPlayer {
  private ctx: AudioContext | null = null;
  private out: GainNode | null = null;
  readonly analyser: AnalyserNode | null = null;
  private loop: { stop: () => void } | null = null;
  private playing = new Set<AudioScheduledSourceNode>();

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
    }
    void this.ctx.resume();
  }

  get ready(): boolean {
    return this.ctx !== null;
  }

  /** One mood; resolves when the moo has finished. */
  play(mood: Mood): Promise<void> {
    const { ctx, out } = this;
    if (!ctx || !out) return Promise.resolve();
    const c = CONTOURS[mood];
    const count = c.count ?? 1;
    let t = ctx.currentTime + 0.02;
    let end = t;
    for (let i = 0; i < count; i++) {
      end = this.moo(ctx, out, t, c);
      t = end + 0.12;
    }
    return new Promise((resolve) => setTimeout(resolve, (end - ctx.currentTime) * 1000));
  }

  private moo(ctx: AudioContext, out: AudioNode, t0: number, c: Contour): number {
    const t1 = t0 + c.dur;
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    const step = c.dur / (c.f0.length - 1);
    osc.frequency.setValueAtTime(c.f0[0] ?? 100, t0);
    c.f0.forEach((f, i) => i > 0 && osc.frequency.linearRampToValueAtTime(f, t0 + i * step));
    const vib = ctx.createOscillator();
    vib.frequency.value = 5.5;
    const vibDepth = ctx.createGain();
    vibDepth.gain.value = 3;
    vib.connect(vibDepth).connect(osc.frequency);
    // Nasal "mmm" opening into "ooo": a lowpass that opens, plus one formant.
    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.frequency.setValueAtTime(300, t0);
    lp.frequency.linearRampToValueAtTime(c.formant * 1.6, t0 + c.dur * 0.35);
    lp.frequency.linearRampToValueAtTime(400, t1);
    const formant = ctx.createBiquadFilter();
    formant.type = "peaking";
    formant.frequency.value = c.formant;
    formant.gain.value = 8;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0, t0);
    env.gain.linearRampToValueAtTime(0.9, t0 + 0.08);
    env.gain.setValueAtTime(0.8, t1 - 0.25);
    env.gain.linearRampToValueAtTime(0, t1);
    osc.connect(lp).connect(formant).connect(env).connect(out);
    for (const s of [osc, vib]) {
      s.start(t0);
      s.stop(t1 + 0.05);
      this.playing.add(s);
      s.onended = () => this.playing.delete(s);
    }
    return t1;
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

export const mooPlayer = new MooPlayer();
