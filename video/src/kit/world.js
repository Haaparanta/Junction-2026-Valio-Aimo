/** World props: sky, stars, lights, ground, pines, snowbanks, buildings, rooms, lamps, signs, live textures. */
import * as THREE from "three";
import { P } from "./palette.js";
import { box, cyl, flat, glow, ico } from "./mat.js";
import { rng } from "./rand.js";

/**
 * A canvas texture that repaints only when its state changes: set(state) merges and repaints if different.
 * draw(g, state, w, h) paints the whole canvas.
 */
export function liveTexture(w, h, draw, initial = {}) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const g = canvas.getContext("2d");
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  let state = { ...initial };
  let key = "";
  const paint = () => {
    const k = JSON.stringify(state);
    if (k === key) return;
    key = k;
    g.clearRect(0, 0, w, h);
    draw(g, state, w, h);
    texture.needsUpdate = true;
  };
  paint();
  return {
    canvas,
    texture,
    get state() {
      return state;
    },
    set(next) {
      state = { ...state, ...next };
      paint();
    },
  };
}

/** A gradient sky dome (seen from inside). Hide it when the camera leaves the planet. */
export function skyDome(top, bottom, { radius = 400, horizon = 0.05 } = {}) {
  const geo = new THREE.SphereGeometry(radius, 24, 12);
  const colors = [];
  const ct = new THREE.Color(top);
  const cb = new THREE.Color(bottom);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i) / radius;
    const k = Math.min(1, Math.max(0, (y - horizon) / 0.6));
    const c = cb.clone().lerp(ct, Math.sqrt(k));
    colors.push(c.r, c.g, c.b);
  }
  geo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false }));
  m.renderOrder = -10;
  return m;
}

export function stars(count = 600, seed = "stars", radius = 300, { minY = 0.05, size = 2.2, color = "#ffffff" } = {}) {
  const r = rng(seed);
  const pos = [];
  for (let i = 0; i < count; i++) {
    const u = r.float(minY, 1);
    const th = r.float(0, Math.PI * 2);
    const s = Math.sqrt(1 - u * u);
    pos.push(radius * s * Math.cos(th), radius * u, radius * s * Math.sin(th));
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return new THREE.Points(geo, new THREE.PointsMaterial({ color, size, sizeAttenuation: false, fog: false }));
}

/**
 * A low sun or a moon with soft shadows, a hemisphere fill and an ambient term.
 * box: half-size of the shadow camera.
 */
export function lights(scene, { dir = [5, 8, 6], color = "#fff1d6", intensity = 2.2, sky = "#bcd4ff", groundColor = "#6b5a4a", hemi = 1.1, ambient = 0.25, box: b = 12, target = [0, 0, 0] } = {}) {
  const sun = new THREE.DirectionalLight(color, intensity);
  sun.position.set(target[0] + dir[0], target[1] + dir[1], target[2] + dir[2]);
  sun.target.position.set(...target);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -b, right: b, top: b, bottom: -b, near: 0.5, far: 80 });
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.02;
  scene.add(sun, sun.target);
  const h = new THREE.HemisphereLight(sky, groundColor, hemi);
  scene.add(h);
  const a = new THREE.AmbientLight("#ffffff", ambient);
  scene.add(a);
  return { sun, hemi: h, ambient: a };
}

/** A ground plane with jittered vertices for a faceted look. */
export function ground(size = 80, color = P.snow, { seed = "ground", jitter = 0.12, segments = 40 } = {}) {
  const geo = new THREE.PlaneGeometry(size, size, segments, segments);
  geo.rotateX(-Math.PI / 2);
  const r = rng(seed);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const z = pos.getZ(i);
    const centre = Math.hypot(x, z) < 6 ? 0.25 : 1;
    pos.setY(i, r.float(-jitter, jitter) * centre);
  }
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, flat(color));
  m.receiveShadow = true;
  return m;
}

/** A faceted pine with snow caps. */
export function pine(h = 4, { seed = 1, snow = true, color = "#2f6b45" } = {}) {
  const g = new THREE.Group();
  const r = rng(`pine${seed}`);
  g.add(cyl(0.12 * h * 0.25, 0.16 * h * 0.25, h * 0.25, 5, P.woodDark, 0, h * 0.12, 0));
  for (let i = 0; i < 3; i++) {
    const rad = h * (0.36 - i * 0.09);
    const ch = h * 0.42;
    const y = h * (0.3 + i * 0.22);
    const c = new THREE.Mesh(new THREE.ConeGeometry(rad, ch, 6), flat(color));
    c.position.y = y + ch / 2;
    c.rotation.y = r.float(0, 1);
    c.castShadow = true;
    g.add(c);
    if (snow) {
      const s = new THREE.Mesh(new THREE.ConeGeometry(rad * 0.62, ch * 0.4, 6), flat(P.snow));
      s.position.y = y + ch * 0.82;
      s.rotation.y = c.rotation.y;
      g.add(s);
    }
  }
  return g;
}

/** A snowbank from jittered icosahedrons. */
export function snowbank(w = 3, { seed = 1, h = 0.8 } = {}) {
  const g = new THREE.Group();
  const r = rng(`bank${seed}`);
  const n = Math.max(2, Math.round(w / 0.8));
  for (let i = 0; i < n; i++) {
    const m = ico(r.float(0.5, 0.8) * h, 0, P.snow, -w / 2 + (i + 0.5) * (w / n), 0.1, r.float(-0.2, 0.2));
    m.scale.set(1.3, r.float(0.6, 0.9), 1);
    m.rotation.set(r.float(0, 3), r.float(0, 3), r.float(0, 3));
    g.add(m);
  }
  return g;
}

/** A flat-shaded building with rows of lit windows. */
export function building(w, h, d, color, { seed = 1, lit = 0.6, windowColor = "#ffd98a", roof = null } = {}) {
  const g = new THREE.Group();
  g.add(box(w, h, d, color, 0, h / 2, 0));
  if (roof) g.add(box(w + 0.3, 0.3, d + 0.3, roof, 0, h + 0.15, 0));
  const r = rng(`bld${seed}`);
  const cols = Math.max(1, Math.floor(w / 1.1));
  const rows = Math.max(1, Math.floor((h - 1) / 1.3));
  for (let i = 0; i < cols; i++) {
    for (let k = 0; k < rows; k++) {
      const on = r.next() < lit;
      const win = new THREE.Mesh(new THREE.PlaneGeometry(0.55, 0.75), on ? glow(windowColor) : flat("#2a3348"));
      win.position.set(-w / 2 + (i + 0.5) * (w / cols), 1.2 + k * 1.3, d / 2 + 0.01);
      g.add(win);
    }
  }
  return g;
}

/** A street lamp with a glowing head (add a glow sprite from fx.js for the halo). */
export function lamp(h = 4.5, color = "#ffd27a") {
  const g = new THREE.Group();
  g.add(cyl(0.06, 0.09, h, 6, "#2b2f38", 0, h / 2, 0));
  g.add(box(0.9, 0.08, 0.12, "#2b2f38", 0.4, h, 0));
  const head = box(0.4, 0.14, 0.3, glow(color), 0.8, h - 0.08, 0);
  head.castShadow = false;
  g.add(head);
  return g;
}

/**
 * An interior open toward +z: floor, back wall, side walls, optional ceiling.
 * Returns the group; its floor is at y = 0, the back wall at z = -d/2.
 */
export function room(w, h, d, { wall = "#f0e6d6", floor = "#c9b08a", side = null, ceiling = null, trim = null } = {}) {
  const g = new THREE.Group();
  const f = box(w, 0.2, d, floor, 0, -0.1, 0);
  const back = box(w, h, 0.2, wall, 0, h / 2, -d / 2);
  const l = box(0.2, h, d, side ?? wall, -w / 2, h / 2, 0);
  const r = box(0.2, h, d, side ?? wall, w / 2, h / 2, 0);
  g.add(f, back, l, r);
  if (ceiling) g.add(box(w, 0.2, d, ceiling, 0, h, 0));
  if (trim) g.add(box(w, 0.3, 0.25, trim, 0, 0.15, -d / 2 + 0.1));
  return g;
}

/** Text on a plane with a canvas texture. Unlit (neon) by default; lit = paper, signs, labels. */
export function label(text, { w = 2, h = 0.6, color = "#ffffff", bg = null, font = "'Archivo Black', 'Arial Black', sans-serif", px = 120, lit = false, glowColor = null, padding = 0.08, rotate = 0 } = {}) {
  const cw = 1024;
  const ch = Math.round((cw * h) / w);
  const tex = liveTexture(cw, ch, (g, s) => {
    if (bg) {
      g.fillStyle = bg;
      g.fillRect(0, 0, cw, ch);
    }
    g.save();
    g.translate(cw / 2, ch / 2);
    g.rotate(rotate);
    g.font = `${s.px}px ${font}`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    const lines = String(s.text).split("\n");
    let size = s.px;
    const maxW = cw * (1 - padding * 2);
    for (const line of lines) {
      const m = g.measureText(line).width;
      if (m > maxW) size = Math.min(size, (s.px * maxW) / m);
    }
    g.font = `${size}px ${font}`;
    if (glowColor) {
      g.shadowColor = glowColor;
      g.shadowBlur = size * 0.35;
    }
    g.fillStyle = s.color;
    lines.forEach((line, i) => g.fillText(line, 0, (i - (lines.length - 1) / 2) * size * 1.1));
    g.restore();
  }, { text, color, px });
  const mat = lit
    ? new THREE.MeshLambertMaterial({ map: tex.texture, transparent: !bg })
    : new THREE.MeshBasicMaterial({ map: tex.texture, transparent: !bg, toneMapped: false, fog: false, depthWrite: !!bg });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  mesh.userData.tex = tex;
  return mesh;
}

/** A neon sign: a dark backing board with glowing text. */
export function neon(text, color, { w = 3, h = 1, board = "#141414" } = {}) {
  const g = new THREE.Group();
  if (board) g.add(box(w + 0.2, h + 0.2, 0.12, board, 0, 0, -0.08));
  const t = label(text, { w, h, color: "#ffffff", glowColor: color, px: 200 });
  t.position.z = 0.0;
  g.add(t);
  const t2 = label(text, { w, h, color, px: 200 });
  t2.position.z = 0.005;
  t2.scale.setScalar(1.0);
  g.add(t2);
  g.userData.text = [t, t2];
  return g;
}

/** A window to the outside: frame, a night-sky pane and two snow-capped silhouettes. */
export function windowPane(w = 1.6, h = 1.8, { sky = "#1b2a5a", frame = "#ffffff" } = {}) {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(new THREE.PlaneGeometry(w, h), glow(sky)));
  g.add(box(w + 0.16, 0.1, 0.1, frame, 0, h / 2, 0.02), box(w + 0.16, 0.1, 0.1, frame, 0, -h / 2, 0.02));
  g.add(box(0.1, h, 0.1, frame, w / 2, 0, 0.02), box(0.1, h, 0.1, frame, -w / 2, 0, 0.02), box(0.06, h, 0.06, frame, 0, 0, 0.02));
  g.add(box(w + 0.3, 0.12, 0.3, frame, 0, -h / 2 - 0.06, 0.12));
  return g;
}
