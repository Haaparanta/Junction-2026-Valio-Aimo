/**
 * 2D text and screens on the output canvas: TikTok-style outlined text, the header, title cards, captions,
 * Mansikki's caption card, stamps, and phone screens in the app's neo-brutal style.
 */
import { CARD_BEATS, BEAT } from "../timeline.js";
import { clamp, E, pop, seg, typed } from "./ease.js";
import { P } from "./palette.js";

export const DISPLAY = "'Archivo Black', 'Arial Black', Impact, sans-serif";
export const UI = "'Space Grotesk', system-ui, sans-serif";

/** Safe areas for TikTok and Reels. */
export const SAFE = { top: 160, bottom: 420, right: 140 };

/** Bold text with a thick outline. Shrinks to maxW. Returns the drawn width. */
export function outlined(g, text, x, y, { size = 80, fill = "#ffffff", stroke = P.ink, lw = null, align = "center", baseline = "middle", font = DISPLAY, scale = 1, rot = 0, alpha = 1, maxW = 900, shadow = true } = {}) {
  if (!text || scale <= 0 || alpha <= 0) return 0;
  g.save();
  g.globalAlpha *= clamp(alpha);
  g.translate(x, y);
  g.rotate(rot);
  g.scale(scale, scale);
  g.font = `${size}px ${font}`;
  let w = g.measureText(text).width;
  let s = size;
  if (w > maxW) {
    s = (size * maxW) / w;
    g.font = `${s}px ${font}`;
    w = maxW;
  }
  g.textAlign = align;
  g.textBaseline = baseline;
  g.lineJoin = "round";
  g.miterLimit = 2;
  if (shadow) {
    g.fillStyle = stroke;
    g.lineWidth = lw ?? s * 0.2;
    g.strokeStyle = stroke;
    g.strokeText(text, s * 0.05, s * 0.07);
  }
  g.lineWidth = lw ?? s * 0.2;
  g.strokeStyle = stroke;
  g.strokeText(text, 0, 0);
  g.fillStyle = fill;
  g.fillText(text, 0, 0);
  g.restore();
  return w;
}

/** The header that stays at the top, inside the safe area. */
export function header(g, lines) {
  lines.forEach((line, i) => outlined(g, line, 540, 214 + i * 72, { size: 62, maxW: 800, lw: 12 }));
}

/** Wraps text into lines that fit maxW with the current font. */
export function wrap(g, text, maxW) {
  const words = String(text).split(" ");
  const lines = [];
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (g.measureText(next).width > maxW && line) {
      lines.push(line);
      line = w;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

export function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.roundRect(x, y, w, h, r);
}

/** A neo-brutal box: fill, thick ink border, hard offset shadow (the app's .card). */
export function brutal(g, x, y, w, h, { fill = "#ffffff", r = 18, bw = 6, shadow = 10, ink = P.ink } = {}) {
  if (shadow) {
    g.fillStyle = ink;
    roundRect(g, x + shadow, y + shadow, w, h, r);
    g.fill();
  }
  g.fillStyle = fill;
  roundRect(g, x, y, w, h, r);
  g.fill();
  g.lineWidth = bw;
  g.strokeStyle = ink;
  g.stroke();
}

/** A chip like the app's .chip. Returns its width. */
export function chip(g, text, x, y, { fill = P.cyan, size = 30, font = UI, weight = 700, h = null } = {}) {
  g.save();
  g.font = `${weight} ${size}px ${font}`;
  const w = g.measureText(text).width + size * 1.1;
  const hh = h ?? size * 1.5;
  g.fillStyle = fill;
  roundRect(g, x, y, w, hh, hh / 2);
  g.fill();
  g.lineWidth = 4;
  g.strokeStyle = P.ink;
  g.stroke();
  g.fillStyle = P.ink;
  g.textAlign = "left";
  g.textBaseline = "middle";
  g.fillText(text, x + size * 0.55, y + hh / 2 + 1);
  g.restore();
  return w;
}

/**
 * The series-style title card over a scene's first beats: the scene dims, the counter slams in,
 * a red strip swipes across, the line types in. t is the scene's local time.
 */
export function card(g, t, { counter, line }) {
  const dur = CARD_BEATS * BEAT;
  if (t >= dur) return;
  const out = seg(t, dur - 0.08, dur);
  g.save();
  g.fillStyle = `rgba(8,10,20,${0.78 * (1 - out)})`;
  g.fillRect(0, 0, 1080, 1920);
  // red strip
  const sw = E.outCubic(seg(t, 0.1, 0.3));
  g.save();
  g.translate(540, 1010);
  g.rotate(-0.06);
  g.fillStyle = P.red;
  g.fillRect(-700, -62, 1400 * sw, 124);
  g.fillStyle = P.ink;
  g.fillRect(-700, 56, 1400 * sw, 12);
  g.restore();
  // counter slams from big to its size
  const k = seg(t, 0, 0.16);
  const scale = (1 + 2.2 * (1 - E.outCubic(k))) * (1 - out * 0.3);
  const jitter = t < 0.3 ? Math.sin(t * 90) * 8 * (1 - seg(t, 0.16, 0.3)) : 0;
  outlined(g, counter, 540 + jitter, 820, { size: 190, scale, alpha: Math.min(1, k * 3) * (1 - out), maxW: 860, lw: 26, fill: P.yellow });
  // the line types in on the strip
  const text = typed(line, t, 0.22, 70);
  g.save();
  g.translate(540, 1010);
  g.rotate(-0.06);
  g.font = `700 54px ${UI}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillStyle = "#ffffff";
  g.globalAlpha = 1 - out;
  g.fillText(text, 0, 2);
  g.restore();
  g.restore();
}

/** A spoken line as a pop-in caption: big outlined text. k is the pop amount (use ease.pop). */
export function caption(g, text, x, y, k, opts = {}) {
  if (k <= 0) return;
  outlined(g, text, x, y, { size: 74, scale: k, maxW: 860, ...opts });
}

/** A TikTok "text with background" caption: white rounded box, black text. */
export function boxCaption(g, text, x, y, k, { size = 52, fill = "#ffffff", color = P.ink, maxW = 820 } = {}) {
  if (k <= 0) return;
  g.save();
  g.translate(x, y);
  g.scale(k, k);
  g.font = `700 ${size}px ${UI}`;
  const lines = wrap(g, text, maxW);
  const lh = size * 1.2;
  const w = Math.max(...lines.map((l) => g.measureText(l).width)) + size;
  const h = lines.length * lh + size * 0.5;
  g.fillStyle = fill;
  roundRect(g, -w / 2, -h / 2, w, h, 16);
  g.fill();
  g.fillStyle = color;
  g.textAlign = "center";
  g.textBaseline = "middle";
  lines.forEach((l, i) => g.fillText(l, 0, -h / 2 + size * 0.25 + lh * (i + 0.5)));
  g.restore();
}

/**
 * Mansikki's caption, like the app: her voice is muted, so a card carries the real words.
 * A "MOO." in big letters and the precise answer under it.
 */
export function cowCaption(g, text, y, k, { moo = "MOO.", mood = "happy" } = {}) {
  if (k <= 0) return;
  const w = 860;
  g.save();
  g.translate(540, y);
  g.scale(k, k);
  g.font = `700 44px ${UI}`;
  const lines = wrap(g, text, w - 60);
  const h = 96 + lines.length * 54;
  brutal(g, -w / 2, -h / 2, w, h, { fill: P.paper, shadow: 10 });
  chip(g, "Mansikki 🐄", -w / 2 + 24, -h / 2 - 26, { fill: mood === "alarmed" ? P.red : P.pink, size: 32 });
  g.fillStyle = P.ink;
  g.textAlign = "left";
  g.textBaseline = "top";
  g.font = `700 44px ${UI}`;
  lines.forEach((l, i) => g.fillText(l, -w / 2 + 30, -h / 2 + 40 + i * 54));
  g.restore();
  if (moo) outlined(g, moo, 540 + 300, y - (96 + lines.length * 54) / 2 - 40, { size: 70, scale: k, rot: 0.12, fill: mood === "alarmed" ? P.red : P.pink });
}

/** A rubber stamp that slams in, rotated. */
export function stamp(g, text, x, y, t, at, { color = P.red, rot = -0.12, size = 96, fill = null } = {}) {
  if (t < at) return;
  const k = seg(t, at, at + 0.14);
  const s = 1 + 1.6 * (1 - E.outCubic(k));
  g.save();
  g.translate(x, y);
  g.rotate(rot);
  g.scale(s, s);
  g.globalAlpha = Math.min(1, k * 2);
  g.font = `${size}px ${DISPLAY}`;
  const w = g.measureText(text).width + size * 0.7;
  const h = size * 1.35;
  if (fill) {
    g.fillStyle = fill;
    roundRect(g, -w / 2, -h / 2, w, h, 14);
    g.fill();
  }
  g.lineWidth = size * 0.12;
  g.strokeStyle = color;
  roundRect(g, -w / 2, -h / 2, w, h, 14);
  g.stroke();
  g.fillStyle = color;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(text, 0, size * 0.04);
  g.restore();
}

/**
 * A phone in 2D with a screen in the app's style. drawScreen(sg, w, h) paints inside the screen,
 * with the origin at its top-left corner.
 */
export function phone(g, cx, cy, k, drawScreen, { w = 520, h = 1000, rot = 0 } = {}) {
  if (k <= 0) return;
  g.save();
  g.translate(cx, cy);
  g.rotate(rot);
  g.scale(k, k);
  g.fillStyle = P.ink;
  roundRect(g, -w / 2 + 14, -h / 2 + 18, w, h, 60);
  g.fill();
  g.fillStyle = "#1c1c1e";
  roundRect(g, -w / 2, -h / 2, w, h, 60);
  g.fill();
  const m = 18;
  const sw = w - m * 2;
  const sh = h - m * 2;
  g.save();
  roundRect(g, -w / 2 + m, -h / 2 + m, sw, sh, 46);
  g.clip();
  g.translate(-w / 2 + m, -h / 2 + m);
  appBackground(g, sw, sh);
  drawScreen(g, sw, sh);
  g.restore();
  g.fillStyle = "#1c1c1e";
  roundRect(g, -60, -h / 2 + 26, 120, 30, 15);
  g.fill();
  g.restore();
}

/** The app's paper background with its dot grid and the top bar. */
export function appBackground(g, w, h, { persona = "cow" } = {}) {
  g.fillStyle = P.paper;
  g.fillRect(0, 0, w, h);
  g.fillStyle = "rgba(17,17,17,0.18)";
  for (let x = 11; x < w; x += 22) for (let y = 11; y < h; y += 22) g.fillRect(x, y, 2, 2);
  // top bar: logo, title
  const accent = persona === "cow" ? P.pink : P.yellow;
  brutal(g, 22, 64, 54, 54, { fill: accent, r: 10, bw: 4, shadow: 4 });
  g.fillStyle = P.ink;
  g.font = `30px ${DISPLAY}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText("V", 49, 92);
  g.textAlign = "left";
  g.font = `26px ${DISPLAY}`;
  g.fillText("Valio Aimo", 92, 84);
  g.font = `700 17px ${UI}`;
  g.fillText("AI ORDERING · MANSIKKI 🐄", 92, 108);
}

/** One basket line in app style: name, amount, and a status (ok | missing | pending). */
export function basketLine(g, x, y, w, name, qty, status = "ok", k = 1) {
  if (k <= 0) return;
  g.save();
  g.translate(x + w / 2, y);
  g.scale(k, k);
  g.translate(-w / 2, 0);
  const fill = status === "missing" ? "#ffd6d6" : "#ffffff";
  brutal(g, 0, 0, w, 74, { fill, r: 12, bw: 4, shadow: 5 });
  g.fillStyle = P.ink;
  g.font = `700 28px ${UI}`;
  g.textAlign = "left";
  g.textBaseline = "middle";
  g.fillText(name, 18, 37);
  g.textAlign = "right";
  if (status === "missing") {
    g.fillStyle = "#b00020";
    g.font = `22px ${DISPLAY}`;
    g.fillText("NOT FOUND", w - 16, 37);
  } else {
    g.font = `700 26px ${UI}`;
    g.fillText(qty, w - 56, 37);
    g.fillStyle = status === "ok" ? P.lime : P.yellow;
    g.beginPath();
    g.arc(w - 30, 37, 14, 0, Math.PI * 2);
    g.fill();
    g.lineWidth = 3;
    g.strokeStyle = P.ink;
    g.stroke();
  }
  g.restore();
}

/** A big app button with a hard shadow; pressed = pushed into its shadow. */
export function button(g, text, x, y, w, h, { fill = P.yellow, pressed = 0, size = 36 } = {}) {
  const d = 8 * clamp(pressed);
  brutal(g, x + d, y + d, w, h, { fill, r: 14, bw: 5, shadow: 8 - d });
  g.fillStyle = P.ink;
  g.font = `${size}px ${DISPLAY}`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(text, x + d + w / 2, y + d + h / 2 + 2);
}

/** A notification banner sliding down from the top of the screen area. */
export function banner(g, x, y, w, k, title, body, { fill = "#ffffff", icon = "🐄" } = {}) {
  if (k <= 0) return;
  g.save();
  g.translate(0, (1 - E.outBack(clamp(k))) * -160);
  brutal(g, x, y, w, 120, { fill, r: 22, bw: 5, shadow: 8 });
  g.font = "52px sans-serif";
  g.textBaseline = "middle";
  g.textAlign = "left";
  g.fillText(icon, x + 22, y + 60);
  g.fillStyle = P.ink;
  g.font = `26px ${DISPLAY}`;
  g.fillText(title, x + 96, y + 42);
  g.font = `700 26px ${UI}`;
  g.fillText(body, x + 96, y + 82);
  g.restore();
}

/** A stopwatch-style badge: "5 s". */
export function timerBadge(g, text, x, y, k, fill = P.lime) {
  if (k <= 0) return;
  g.save();
  g.translate(x, y);
  g.scale(k, k);
  g.rotate(-0.08);
  chip(g, text, -90, -30, { fill, size: 40 });
  g.restore();
}

export { pop };
