/**
 * One requestAnimationFrame loop writes CSS variables on the SVG root: no React render per frame (PLAN M16.2).
 * Aino's mouth follows the agent's output audio; Mansikki's follows the moo player.
 */
import { useEffect, type RefObject } from "react";
import { useConversationControls } from "@elevenlabs/react";
import { mooPlayer } from "../cow/MooPlayer";
import { ui } from "../voice/store";
import { bands, energy, follow, gain, hysteresis, shapeFor, type MouthShape } from "./mouth";

export function useAvatarDriver(ref: RefObject<SVGSVGElement | null>) {
  const { getOutputByteFrequencyData } = useConversationControls();

  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let raf = 0;
    let last = performance.now();
    let open = 0;
    let peak = 0.2;
    let hyst = { shape: "M" as MouthShape, candidate: "M" as MouthShape, count: 0 };
    let nextBlink = last + 2000 + Math.random() * 3000;
    let blinkUntil = 0;
    let mooBuf: Uint8Array<ArrayBuffer> | null = null;

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const el = ref.current;
      if (!el) return;
      const dt = Math.min(100, now - last);
      last = now;
      let data: ArrayLike<number> = [];
      const cow = ui.get().persona === "cow";
      if (cow && mooPlayer.analyser) {
        const a = mooPlayer.analyser;
        if (!mooBuf || mooBuf.length !== a.frequencyBinCount) mooBuf = new Uint8Array(a.frequencyBinCount);
        a.getByteFrequencyData(mooBuf);
        data = mooBuf.subarray(0, Math.floor(mooBuf.length * 0.36)); // ~0-8 kHz at 44.1 kHz
      } else if (ui.get().phase === "live") {
        try {
          data = getOutputByteFrequencyData();
        } catch {
          data = []; // "No active conversation"
        }
      }
      const b = bands(data);
      const g = gain(peak, energy(b), dt);
      peak = g.peak;
      const target = g.level < 0.08 ? 0 : g.level;
      open = follow(open, reduced?.matches ? Math.min(target, 0.3) : target, dt);
      hyst = hysteresis(hyst, shapeFor(b, open));
      if (now > nextBlink) {
        blinkUntil = now + 120;
        nextBlink = now + 2000 + Math.random() * 3000;
      }
      el.style.setProperty("--mouth-open", open.toFixed(3));
      el.style.setProperty("--blink", now < blinkUntil ? "0.1" : "1");
      el.style.setProperty("--breath", reduced?.matches ? "0" : Math.sin(now / 1400).toFixed(3));
      if (el.dataset.mouth !== hyst.shape) el.dataset.mouth = hyst.shape;
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [ref, getOutputByteFrequencyData]);
}
