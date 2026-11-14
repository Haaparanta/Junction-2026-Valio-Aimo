/**
 * Effects. 3D: snowfall, bursts (parabolas with an analytic landing time), drops, rings, glow sprites,
 * steam, camera shake. 2D (drawn on the output canvas): speed lines, flash, vignette, grain, sparkle.
 * Everything is a function of t.
 */
import * as THREE from "three";
import { clamp, E, seg } from "./ease.js";
import { noise1, rng } from "./rand.js";

let dotTexture = null;
export function roundDot() {
  if (dotTexture) return dotTexture;
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.6, "rgba(255,255,255,0.9)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  dotTexture = new THREE.CanvasTexture(c);
  return dotTexture;
}

const glowTextures = new Map();
function glowTexture(color) {
  if (glowTextures.has(color)) return glowTextures.get(color);
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  const col = new THREE.Color(color);
  const rgb = `${Math.round(col.r * 255)},${Math.round(col.g * 255)},${Math.round(col.b * 255)}`;
  grad.addColorStop(0, `rgba(${rgb},1)`);
  grad.addColorStop(0.25, `rgba(${rgb},0.55)`);
  grad.addColorStop(1, `rgba(${rgb},0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  glowTextures.set(color, t);
  return t;
}

/** An additive glow sprite. */
export function glowSprite(color, size = 1, opacity = 1) {
  const s = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: glowTexture(color), blending: THREE.AdditiveBlending, transparent: true, depthWrite: false, opacity, fog: false }),
  );
  s.scale.setScalar(size);
  return s;
}

/** Falling snow in a box, by formula: y wraps, x sways. */
export function snowfall({ count = 800, seed = "snow", x = [-15, 15], y = [0, 14], z = [-15, 8], speed = [0.8, 1.6], size = 0.09, color = "#ffffff", sway = 0.4 } = {}) {
  const r = rng(seed);
  const base = [];
  for (let i = 0; i < count; i++) base.push([r.float(...x), r.float(0, 1), r.float(...z), r.float(...speed), r.float(0, 6.28), r.float(0.5, 1.5)]);
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 3);
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const points = new THREE.Points(geo, new THREE.PointsMaterial({ color, size, map: roundDot(), transparent: true, depthWrite: false, alphaTest: 0.05 }));
  points.frustumCulled = false;
  const h = y[1] - y[0];
  return {
    object: points,
    update(t, wind = 0) {
      for (let i = 0; i < count; i++) {
        const [bx, by, bz, sp, ph, f] = base[i];
        const yy = y[1] - (((by * h + sp * t) % h) + h) % h;
        pos[i * 3] = bx + Math.sin(t * f + ph) * sway + wind * (y[1] - yy) * 0.2;
        pos[i * 3 + 1] = yy;
        pos[i * 3 + 2] = bz;
      }
      geo.attributes.position.needsUpdate = true;
    },
  };
}

/**
 * Height of something dropped at `at` from y0 that lands on y1 (gravity g); after landing it bounces a little.
 * Returns { y, landed, tLand }.
 */
export function drop(t, at, y0, y1, g = 22, bounce = 0.25) {
  const tLand = Math.sqrt((2 * Math.max(0, y0 - y1)) / g);
  const tau = t - at;
  if (tau <= 0) return { y: y0, landed: false, tLand: at + tLand, falling: false };
  if (tau < tLand) return { y: y0 - 0.5 * g * tau * tau, landed: false, tLand: at + tLand, falling: true };
  const b = tau - tLand;
  const v = g * tLand * bounce;
  const tb = (2 * v) / g;
  const y = b < tb ? y1 + v * b - 0.5 * g * b * b : y1;
  return { y, landed: true, tLand: at + tLand, falling: false };
}

/**
 * A burst of particles thrown from origin at `at`: parabolas with gravity that rest where they land on `floor`.
 * make(i, r) returns a mesh. dir: [x, y, z] main direction (normalised inside), spread in radians.
 */
export function burst({ count = 40, seed = "burst", origin = [0, 0, 0], at = 0, speed = [4, 8], dir = [0, 1, 0], spread = 0.6, gravity = 9.8, floor = 0, make, spin = 6, life = Infinity, scale = 1 }) {
  const r = rng(seed);
  const group = new THREE.Group();
  const d = new THREE.Vector3(...dir).normalize();
  const parts = [];
  for (let i = 0; i < count; i++) {
    const mesh = make(i, r);
    mesh.visible = false;
    group.add(mesh);
    // a random direction inside a cone around d
    const a = r.float(0, Math.PI * 2);
    const b = r.float(0, spread);
    const perp1 = new THREE.Vector3().crossVectors(d, Math.abs(d.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0)).normalize();
    const perp2 = new THREE.Vector3().crossVectors(d, perp1);
    const v = d.clone().multiplyScalar(Math.cos(b)).add(perp1.multiplyScalar(Math.sin(b) * Math.cos(a))).add(perp2.multiplyScalar(Math.sin(b) * Math.sin(a)));
    v.multiplyScalar(r.float(...speed));
    const delay = r.float(0, 0.12);
    const vy = v.y;
    const tLand = (vy + Math.sqrt(vy * vy + 2 * gravity * Math.max(0, origin[1] - floor))) / gravity;
    parts.push({ mesh, v, delay, tLand, rot: [r.float(-spin, spin), r.float(-spin, spin), r.float(-spin, spin)], s: r.float(0.7, 1.2) * scale });
  }
  return {
    object: group,
    update(t) {
      for (const p of parts) {
        const tau = t - at - p.delay;
        p.mesh.visible = tau >= 0 && tau < life;
        if (!p.mesh.visible) continue;
        const tt = Math.min(tau, p.tLand);
        p.mesh.position.set(origin[0] + p.v.x * tt, origin[1] + p.v.y * tt - 0.5 * gravity * tt * tt, origin[2] + p.v.z * tt);
        p.mesh.rotation.set(p.rot[0] * tt, p.rot[1] * tt, p.rot[2] * tt);
        const fade = life < Infinity ? 1 - seg(tau, life * 0.6, life) : 1;
        p.mesh.scale.setScalar(p.s * Math.min(1, tau * 12) * fade);
      }
    },
  };
}

/** A shock ring that grows and fades; it turns to face the camera each frame. */
export function ring(color = "#ffffff", { inner = 0.8, outer = 1 } = {}) {
  const m = new THREE.Mesh(
    new THREE.RingGeometry(inner, outer, 40),
    new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide, depthWrite: false, fog: false, toneMapped: false }),
  );
  m.visible = false;
  return {
    object: m,
    update(t, at, camera, { dur = 0.6, size = 8 } = {}) {
      const k = seg(t, at, at + dur);
      m.visible = t >= at && k < 1;
      if (!m.visible) return;
      m.lookAt(camera.position);
      m.scale.setScalar(0.2 + E.outCubic(k) * size);
      m.material.opacity = 1 - k;
    },
  };
}

/** Steam puffs rising from a point, looping by formula. */
export function steam({ count = 24, seed = "steam", origin = [0, 0, 0], height = 4, period = 2.5, spread = 1.2, color = "#ffffff", size = 1.6, opacity = 0.35 } = {}) {
  const r = rng(seed);
  const group = new THREE.Group();
  const parts = [];
  for (let i = 0; i < count; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: roundDot(), color, transparent: true, depthWrite: false, opacity }));
    group.add(s);
    parts.push({ s, ph: r.float(0, 1), dx: r.float(-spread, spread), dz: r.float(-spread * 0.5, spread * 0.5), wob: r.float(0, 6) });
  }
  return {
    object: group,
    /** boost > 1 makes a big burst (water on the stones). */
    update(t, boost = 1) {
      for (const p of parts) {
        const k = (((t / period + p.ph) % 1) + 1) % 1;
        p.s.position.set(origin[0] + p.dx * k + Math.sin(t + p.wob) * 0.2, origin[1] + k * height * boost, origin[2] + p.dz * k);
        p.s.scale.setScalar(size * (0.4 + k) * Math.sqrt(boost));
        p.s.material.opacity = opacity * Math.sin(Math.PI * k) * Math.min(1.6, boost);
      }
    },
  };
}

/** Camera shake offsets [dx, dy, roll] for an impact at `at`. */
export function shake(t, at, { dur = 0.5, amp = 0.3, seed = 1 } = {}) {
  if (t < at || t > at + dur) return [0, 0, 0];
  const k = 1 - (t - at) / dur;
  const f = 38;
  return [noise1(t * f, seed) * amp * k, noise1(t * f, seed + 7) * amp * k, noise1(t * f, seed + 13) * amp * 0.08 * k];
}

// ---------- 2D effects on the output canvas ----------

/** Anime speed lines toward a centre point. */
export function speedLines(g, t, k, { cx = 540, cy = 900, color = "rgba(255,255,255,0.85)", count = 70, inner = 380, seed = 3 } = {}) {
  if (k <= 0) return;
  const r = rng(seed * 1000 + Math.floor(t * 30));
  g.save();
  g.fillStyle = color;
  g.globalAlpha = clamp(k);
  for (let i = 0; i < count; i++) {
    const a = r.float(0, Math.PI * 2);
    const w = r.float(0.004, 0.012);
    const r0 = inner + r.float(0, 200);
    const r1 = 1600;
    g.beginPath();
    g.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
    g.lineTo(cx + Math.cos(a - w) * r1, cy + Math.sin(a - w) * r1);
    g.lineTo(cx + Math.cos(a + w) * r1, cy + Math.sin(a + w) * r1);
    g.closePath();
    g.fill();
  }
  g.restore();
}

export function flash(g, k, color = "#ffffff") {
  if (k <= 0) return;
  g.save();
  g.globalAlpha = clamp(k);
  g.fillStyle = color;
  g.fillRect(0, 0, g.canvas.width, g.canvas.height);
  g.restore();
}

export function vignette(g, k = 0.5) {
  if (k <= 0) return;
  const { width: w, height: h } = g.canvas;
  const grad = g.createRadialGradient(w / 2, h / 2, h * 0.25, w / 2, h / 2, h * 0.75);
  grad.addColorStop(0, "rgba(0,0,0,0)");
  grad.addColorStop(1, `rgba(0,0,0,${k})`);
  g.fillStyle = grad;
  g.fillRect(0, 0, w, h);
}

let grainCanvas = null;
export function grain(g, t, k = 0.08) {
  if (k <= 0) return;
  if (!grainCanvas) {
    grainCanvas = document.createElement("canvas");
    grainCanvas.width = grainCanvas.height = 256;
    const gg = grainCanvas.getContext("2d");
    const img = gg.createImageData(256, 256);
    const r = rng("grain");
    for (let i = 0; i < img.data.length; i += 4) {
      const v = r.int(0, 255);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    gg.putImageData(img, 0, 0);
  }
  const r = rng(Math.floor(t * 30) + 77);
  g.save();
  g.globalAlpha = k;
  g.globalCompositeOperation = "overlay";
  const ox = -r.int(0, 255);
  const oy = -r.int(0, 255);
  for (let x = ox; x < g.canvas.width; x += 256) for (let y = oy; y < g.canvas.height; y += 256) g.drawImage(grainCanvas, x, y);
  g.restore();
}

/** A four-point sparkle that pops and spins. */
export function sparkle(g, x, y, t, at, { size = 60, color = "#ffffff", dur = 0.6 } = {}) {
  const k = seg(t, at, at + dur);
  if (t < at || k >= 1) return;
  const s = size * Math.sin(Math.PI * k);
  g.save();
  g.translate(x, y);
  g.rotate(k * 1.5);
  g.fillStyle = color;
  g.beginPath();
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4;
    const rr = i % 2 === 0 ? s : s * 0.22;
    g.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
  }
  g.closePath();
  g.fill();
  g.restore();
}
