/**
 * The player. Every frame is a function of its time: frame(T) builds the view of the segment at T (once),
 * sets everything from the local time, renders WebGL into a 2D output canvas and draws the overlays on top.
 * The output canvas is what the page shows and what the export encodes.
 *
 * Address: #view=<id|all>&t=<local seconds> survives the automatic reloads.
 * Console: player.frame(view, t) · await player.render(view, { saveTo: 'out' }) · await player.sound()
 *          · await player.sheet(view) · await player.voiceStats()
 */
import * as THREE from "three";
import { buildMix } from "./audio/mix.js";
import { exportMp4 } from "./export.js";
import { card, header, SAFE } from "./kit/text2d.js";
import { FPS, H, HEADER, SEGMENTS, TOTAL, W, segmentAt } from "./timeline.js";

const $ = (id) => document.getElementById(id);
const out = $("out");
const g = out.getContext("2d");

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap; // r186: PCFSoftShadowMap is gone

const state = { view: "all", T: 0, playing: false, loop: true, muted: false, safe: false, exporting: false };
const views = new Map();
const modules = new Map();

async function loadModules() {
  for (const s of SEGMENTS) {
    try {
      modules.set(s.view, await import(`./views/${s.view}.js`));
    } catch (e) {
      console.warn(`view ${s.view}: ${e.message}; using a placeholder`);
      modules.set(s.view, placeholderModule(s.view));
    }
  }
}

function placeholderModule(id) {
  return {
    sounds: () => [],
    build() {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#30304a");
      const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 100);
      camera.position.set(0, 0, 5);
      return {
        scene,
        camera,
        update() {},
        overlay(gg) {
          gg.fillStyle = "#fff";
          gg.font = "80px sans-serif";
          gg.textAlign = "center";
          gg.fillText(id, 540, 960);
        },
      };
    },
  };
}

function viewFor(seg) {
  if (!views.has(seg.id)) views.set(seg.id, modules.get(seg.view).build(seg));
  return views.get(seg.id);
}

function range() {
  if (state.view === "all") return [0, TOTAL];
  const s = SEGMENTS.find((x) => x.id === state.view);
  return [s.start, s.end];
}

/** Draws the frame at global time T onto the output canvas. */
function frame(T) {
  const seg = segmentAt(Math.min(T, TOTAL - 1e-6));
  const v = viewFor(seg);
  const t = T - seg.start;
  v.update(t);
  renderer.render(v.scene, v.camera);
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalAlpha = 1;
  g.globalCompositeOperation = "source-over";
  g.drawImage(renderer.domElement, 0, 0, W, H);
  g.save();
  v.overlay?.(g, t);
  g.restore();
  if (seg.card) card(g, t, seg.card);
  if (seg.header) header(g, HEADER);
  if (state.safe && !state.exporting) drawSafe();
  return { seg, t };
}

function drawSafe() {
  g.save();
  g.fillStyle = "rgba(255,0,80,0.22)";
  g.fillRect(0, 0, W, SAFE.top);
  g.fillRect(0, H - SAFE.bottom, W, SAFE.bottom);
  g.fillRect(W - SAFE.right, SAFE.top, SAFE.right, H - SAFE.top - SAFE.bottom);
  g.restore();
}

// ---------- sound ----------
let mix = null;
let ctx = null;
let source = null;
let gainNode = null;
let clockStart = 0;
let wallStart = 0;

async function sound() {
  setStatus("mixing sound…");
  const t0 = performance.now();
  mix = await buildMix(modules);
  setStatus(mix ? `sound ready in ${((performance.now() - t0) / 1000).toFixed(1)} s, peak ${mix.peak.toFixed(3)}` : "no sound");
  return mix?.stats;
}

function startAudio(T) {
  if (!mix?.buffer) return;
  ctx ??= new AudioContext({ sampleRate: mix.buffer.sampleRate });
  if (ctx.state === "suspended") ctx.resume();
  stopAudio();
  gainNode = ctx.createGain();
  gainNode.gain.value = state.muted ? 0 : 1;
  gainNode.connect(ctx.destination);
  source = ctx.createBufferSource();
  source.buffer = mix.buffer;
  source.connect(gainNode);
  source.start(0, T);
  clockStart = ctx.currentTime - T;
}

function stopAudio() {
  if (source) {
    try {
      source.stop();
    } catch {
      /* not started */
    }
    source.disconnect();
    source = null;
  }
}

function clockNow() {
  if (source && ctx) return ctx.currentTime - clockStart;
  return (performance.now() - wallStart) / 1000;
}

// ---------- transport ----------
function play() {
  const [a, b] = range();
  if (state.T < a || state.T >= b - 1 / FPS) state.T = a;
  state.playing = true;
  wallStart = performance.now() - state.T * 1000;
  startAudio(state.T);
  $("play").textContent = "❚❚ Pause";
  requestAnimationFrame(tick);
}

function pause() {
  state.playing = false;
  stopAudio();
  $("play").textContent = "▶ Play";
  show(state.T);
}

function tick() {
  if (!state.playing) return;
  const [a, b] = range();
  let T = clockNow();
  if (T >= b) {
    if (state.loop) {
      T = a;
      wallStart = performance.now() - a * 1000;
      startAudio(a);
    } else {
      state.T = b - 1 / FPS;
      pause();
      return;
    }
  }
  state.T = T;
  show(T, false);
  requestAnimationFrame(tick);
}

function show(T, writeHash = true) {
  const { seg, t } = frame(T);
  const [a, b] = range();
  $("scrub").value = String(Math.round(((T - a) / (b - a)) * 1000));
  $("time").textContent = `T ${T.toFixed(3)} / ${TOTAL.toFixed(2)} s\n${seg.id} t ${t.toFixed(3)} / ${seg.duration.toFixed(3)}\nframe ${Math.round(T * FPS)}`;
  if (writeHash) {
    const local = state.view === "all" ? T : T - a;
    history.replaceState(null, "", `#view=${state.view}&t=${local.toFixed(3)}`);
  }
}

function setStatus(s) {
  $("status").textContent = s;
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const v = p.get("view");
  if (v && (v === "all" || SEGMENTS.some((s) => s.id === v))) state.view = v;
  const [a] = range();
  state.T = a + Number(p.get("t") ?? 0);
}

function setupUi() {
  const sel = $("view");
  sel.innerHTML = `<option value="all">all (${TOTAL.toFixed(2)} s)</option>${SEGMENTS.map((s) => `<option value="${s.id}">${s.id} (${s.duration.toFixed(2)} s)</option>`).join("")}`;
  sel.value = state.view;
  sel.onchange = () => {
    pause();
    state.view = sel.value;
    state.T = range()[0];
    show(state.T);
  };
  $("play").onclick = () => (state.playing ? pause() : play());
  $("prev").onclick = () => step(-1);
  $("next").onclick = () => step(1);
  $("scrub").oninput = (e) => {
    if (state.playing) pause();
    const [a, b] = range();
    state.T = a + (Number(e.target.value) / 1000) * (b - a);
    show(state.T);
  };
  $("loop").onchange = (e) => (state.loop = e.target.checked);
  $("mute").onchange = (e) => {
    state.muted = e.target.checked;
    if (gainNode) gainNode.gain.value = state.muted ? 0 : 1;
  };
  $("safe").onchange = (e) => {
    state.safe = e.target.checked;
    show(state.T);
  };
  $("render").onclick = () => render(state.view);
  $("sheet").onclick = () => sheet(state.view);
  addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT") return;
    if (e.key === " ") {
      e.preventDefault();
      state.playing ? pause() : play();
    }
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  });
}

function step(n) {
  if (state.playing) pause();
  const f = Math.round(state.T * FPS) + n;
  const [a, b] = range();
  state.T = Math.min(b - 1 / FPS, Math.max(a, f / FPS));
  show(state.T);
}

// ---------- console hooks ----------
function frameAt(view = state.view, t = 0) {
  if (state.playing) pause();
  state.view = view;
  $("view").value = view;
  const [a] = range();
  state.T = a + t;
  show(state.T);
  return out;
}

/** A 3×3 contact sheet of a view, saved to video/out/<name>. */
async function sheet(view = state.view, { name = null, times = null } = {}) {
  const prev = state.view;
  state.view = view;
  const [a, b] = range();
  const dur = b - a;
  const ts = times ?? Array.from({ length: 9 }, (_, i) => 0.15 + (i * (dur - 0.3)) / 8);
  const c = document.createElement("canvas");
  c.width = 1080;
  c.height = 1920;
  const cg = c.getContext("2d");
  cg.fillStyle = "#000";
  cg.fillRect(0, 0, 1080, 1920);
  ts.forEach((t, i) => {
    frame(a + t);
    const x = (i % 3) * 360;
    const y = Math.floor(i / 3) * 640;
    cg.drawImage(out, x, y, 360, 640);
    cg.fillStyle = "rgba(0,0,0,0.6)";
    cg.fillRect(x, y + 610, 120, 30);
    cg.fillStyle = "#fff";
    cg.font = "bold 22px monospace";
    cg.fillText(t.toFixed(2), x + 8, y + 633);
  });
  state.view = prev;
  show(state.T, false);
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
  const file = name ?? `sheet-${view}.jpg`;
  const res = await fetch(`/save?to=out&name=${encodeURIComponent(file)}`, { method: "POST", body: blob });
  const { path } = await res.json();
  setStatus(`sheet saved: ${path}`);
  return path;
}

async function render(view = state.view, { saveTo = null } = {}) {
  if (state.playing) pause();
  if (!mix) await sound();
  state.exporting = true;
  const prev = state.view;
  state.view = view;
  const [a, b] = range();
  try {
    const path = await exportMp4({
      from: a,
      to: b,
      drawFrame: (T) => frame(T),
      canvas: out,
      audio: mix?.buffer ?? null,
      name: `joke-video-${view}.mp4`,
      saveTo,
      onProgress: (k) => setStatus(`rendering ${view}: ${(k * 100).toFixed(0)} %`),
    });
    setStatus(`saved ${path}`);
    return path;
  } finally {
    state.exporting = false;
    state.view = prev;
  }
}

async function voiceStats() {
  return mix?.voices ?? (await sound(), mix?.voices);
}

window.player = { frame: frameAt, render, sound, sheet, voiceStats, state, segments: SEGMENTS };

// ---------- start ----------
async function start() {
  await Promise.all([document.fonts.load("62px 'Archivo Black'"), document.fonts.load("700 40px 'Space Grotesk'"), document.fonts.load("400 40px 'Space Grotesk'")]);
  await loadModules();
  readHash();
  setupUi();
  show(state.T);
  const events = new EventSource("/events");
  events.onmessage = () => {
    if (!state.exporting) location.reload();
  };
  sound().catch((e) => {
    console.error(e);
    setStatus(`sound failed: ${e.message}`);
  });
}

start();
