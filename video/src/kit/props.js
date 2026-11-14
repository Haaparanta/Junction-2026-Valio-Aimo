/** Low-poly props for the sets: food, kitchen, sauna, barn. Each returns a Group with its base at y = 0. */
import * as THREE from "three";
import { P } from "./palette.js";
import { box, cyl, flat, glow, ico, pivot } from "./mat.js";
import { label } from "./world.js";

/** A Valio-style milk carton: white with a coloured band, a gable top and the product name in our own lettering. */
export function carton(word = "EILA", { color = P.eila, s = 1 } = {}) {
  const g = new THREE.Group();
  g.add(box(0.36 * s, 0.6 * s, 0.36 * s, "#ffffff", 0, 0.3 * s, 0));
  g.add(box(0.37 * s, 0.22 * s, 0.37 * s, color, 0, 0.2 * s, 0));
  const top = new THREE.Mesh(new THREE.ConeGeometry(0.26 * s, 0.2 * s, 4), flat("#ffffff"));
  top.position.y = 0.7 * s;
  top.rotation.y = Math.PI / 4;
  g.add(top);
  const l = label(word, { w: 0.34 * s, h: 0.12 * s, color: P.ink, px: 150, lit: true });
  l.position.set(0, 0.44 * s, 0.186 * s);
  g.add(l);
  return g;
}

/** A plastic crate of cartons. */
export function crate(color = P.yellow, word = "VALIO EILA", { cols = 3, rows = 2 } = {}) {
  const g = new THREE.Group();
  const w = cols * 0.42 + 0.1;
  const d = rows * 0.42 + 0.1;
  g.add(box(w, 0.08, d, color, 0, 0.04, 0));
  g.add(box(w, 0.36, 0.06, color, 0, 0.22, d / 2), box(w, 0.36, 0.06, color, 0, 0.22, -d / 2));
  g.add(box(0.06, 0.36, d, color, w / 2, 0.22, 0), box(0.06, 0.36, d, color, -w / 2, 0.22, 0));
  for (let i = 0; i < cols; i++) {
    for (let k = 0; k < rows; k++) {
      const c = carton("EILA", { color: P.eila, s: 0.95 });
      c.position.set(-w / 2 + 0.26 + i * 0.42, 0.08, -d / 2 + 0.26 + k * 0.42);
      g.add(c);
    }
  }
  const l = label(word, { w: w * 0.9, h: 0.22, color: P.ink, bg: "#ffffff", px: 120, lit: true });
  l.position.set(0, 0.24, d / 2 + 0.04);
  g.add(l);
  return g;
}

export function table(w = 3, d = 1.4, h = 1.2, { top = P.wood, legs = P.woodDark, cloth = null } = {}) {
  const g = new THREE.Group();
  g.add(box(w, 0.12, d, cloth ?? top, 0, h, 0));
  for (const x of [w / 2 - 0.12, -w / 2 + 0.12]) for (const z of [d / 2 - 0.12, -d / 2 + 0.12]) g.add(box(0.1, h, 0.1, legs, x, h / 2, z));
  return g;
}

export function counter(w = 4, d = 1.2, h = 1.4, { top = P.steel, front = "#9aa5b1" } = {}) {
  const g = new THREE.Group();
  g.add(box(w, h - 0.1, d, front, 0, (h - 0.1) / 2, 0));
  g.add(box(w + 0.1, 0.1, d + 0.1, top, 0, h - 0.05, 0));
  return g;
}

/** A fridge with a door that opens (door pivot rotates around y), and a light inside. */
export function fridge({ color = "#e9eef2" } = {}) {
  const g = new THREE.Group();
  g.add(box(1.6, 0.12, 1.2, color, 0, 0.06, 0));
  g.add(box(1.6, 0.12, 1.2, color, 0, 3.24, 0));
  g.add(box(0.12, 3.3, 1.2, color, 0.74, 1.65, 0), box(0.12, 3.3, 1.2, color, -0.74, 1.65, 0));
  g.add(box(1.6, 3.3, 0.12, color, 0, 1.65, -0.56));
  const inside = new THREE.Mesh(new THREE.PlaneGeometry(1.36, 3.0), glow("#eaf6ff"));
  inside.position.set(0, 1.65, -0.49);
  g.add(inside);
  for (const y of [0.9, 1.7, 2.5]) g.add(box(1.36, 0.04, 1.0, glow("#cfe7ff", { opacity: 0.85 }), 0, y, -0.02));
  const door = pivot(0.8, 0, 0.6, box(1.6, 3.3, 0.16, color, -0.8, 1.65, 0.08), box(0.08, 0.8, 0.1, "#9aa5b1", -1.45, 1.9, 0.2));
  g.add(door);
  g.userData.door = door;
  return g;
}

export function chocolate() {
  const g = new THREE.Group();
  g.add(box(0.7, 0.08, 0.34, "#5a2d17", 0, 0.04, 0));
  g.add(box(0.5, 0.09, 0.35, P.blue, 0.12, 0.05, 0));
  return g;
}

export function iceCream() {
  const g = new THREE.Group();
  g.add(cyl(0.26, 0.22, 0.34, 8, P.pink, 0, 0.17, 0));
  g.add(cyl(0.27, 0.27, 0.06, 8, "#ffffff", 0, 0.37, 0));
  return g;
}

export function strawberry(s = 1) {
  const g = new THREE.Group();
  const b = new THREE.Mesh(new THREE.ConeGeometry(0.16 * s, 0.3 * s, 6), flat("#e8253f"));
  b.rotation.x = Math.PI;
  b.position.y = 0.15 * s;
  b.castShadow = true;
  g.add(b);
  g.add(box(0.2 * s, 0.05 * s, 0.2 * s, "#3fa34d", 0, 0.31 * s, 0));
  return g;
}

export function egg(s = 1) {
  const m = ico(0.14 * s, 0, "#fff3dd", 0, 0.16 * s, 0);
  m.scale.set(1, 1.3, 1);
  const g = new THREE.Group();
  g.add(m);
  return g;
}

/** A bag (flour, sugar) or a jar, with a word. */
export function bag(word, color = "#ffffff", { s = 1 } = {}) {
  const g = new THREE.Group();
  g.add(box(0.5 * s, 0.7 * s, 0.3 * s, color, 0, 0.35 * s, 0));
  g.add(box(0.46 * s, 0.1 * s, 0.26 * s, color, 0, 0.75 * s, 0));
  const l = label(word, { w: 0.46 * s, h: 0.14 * s, color: P.ink, px: 140, lit: true });
  l.position.set(0, 0.4 * s, 0.155 * s);
  g.add(l);
  return g;
}

export function jar(color = "#c41e3a") {
  const g = new THREE.Group();
  g.add(cyl(0.18, 0.18, 0.36, 8, color, 0, 0.18, 0));
  g.add(cyl(0.19, 0.19, 0.08, 8, P.yellow, 0, 0.4, 0));
  return g;
}

/** A Valio voi pack: a golden wrapper with a blue band and the name. */
export function butter(s = 1) {
  const g = new THREE.Group();
  g.add(box(0.6 * s, 0.3 * s, 0.36 * s, P.voi, 0, 0.15 * s, 0));
  g.add(box(0.61 * s, 0.1 * s, 0.37 * s, P.valio, 0, 0.2 * s, 0));
  const l = label("VALIO VOI", { w: 0.5 * s, h: 0.1 * s, color: "#ffffff", px: 140, lit: true });
  l.position.set(0, 0.2 * s, 0.187 * s);
  g.add(l);
  return g;
}

/** A tub (PROfeel rahka, maitorahka): body colour, lid colour, name on the side. */
export function tub(word = "PROfeel", { body = P.profeel, lid = P.pink, text = "#ffffff", s = 1 } = {}) {
  const g = new THREE.Group();
  g.add(cyl(0.22 * s, 0.18 * s, 0.3 * s, 8, body, 0, 0.15 * s, 0));
  g.add(cyl(0.235 * s, 0.235 * s, 0.04 * s, 8, lid, 0, 0.32 * s, 0));
  const l = label(word, { w: 0.34 * s, h: 0.1 * s, color: text, px: 150, lit: true });
  l.position.set(0, 0.16 * s, 0.205 * s);
  g.add(l);
  return g;
}

/** A wedge of Valio AURA blue cheese: pale with blue veins, a blue wrapper band. */
export function auraWedge(s = 1) {
  const g = new THREE.Group();
  const shape = new THREE.Shape([new THREE.Vector2(0, 0), new THREE.Vector2(0.7 * s, 0.2 * s), new THREE.Vector2(0, 0.4 * s)]);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.3 * s, bevelEnabled: false });
  geo.translate(-0.25 * s, -0.2 * s, -0.15 * s);
  const m = new THREE.Mesh(geo, flat("#f4edd8"));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.15 * s;
  m.castShadow = true;
  g.add(m);
  for (let i = 0; i < 6; i++) g.add(box(0.06 * s, 0.31 * s, 0.03 * s, "#4a78b8", -0.15 * s + (i % 3) * 0.12 * s, 0.15 * s, -0.08 * s + Math.floor(i / 3) * 0.13 * s));
  const l = label("AURA", { w: 0.3 * s, h: 0.12 * s, color: "#ffffff", bg: P.aura, px: 150, lit: true });
  l.position.set(-0.24 * s, 0.15 * s, 0.01);
  l.rotation.y = -Math.PI / 2;
  g.add(l);
  return g;
}

/** A block of Valio Oltermanni: yellow cheese with an orange label. */
export function cheeseBlock(word = "OLTERMANNI", s = 1) {
  const g = new THREE.Group();
  g.add(box(0.6 * s, 0.26 * s, 0.4 * s, "#ffd76a", 0, 0.13 * s, 0));
  g.add(box(0.61 * s, 0.12 * s, 0.41 * s, P.olter, 0, 0.13 * s, 0));
  const l = label(word, { w: 0.56 * s, h: 0.1 * s, color: "#ffffff", px: 140, lit: true });
  l.position.set(0, 0.13 * s, 0.207 * s);
  g.add(l);
  return g;
}

/** A big shopping basket (the app's basket), open on top. */
export function basket(w = 2.4, d = 1.6, h = 1.0, color = P.yellow) {
  const g = new THREE.Group();
  g.add(box(w, 0.1, d, color, 0, 0.05, 0));
  g.add(box(w, h, 0.08, color, 0, h / 2, d / 2), box(w, h, 0.08, color, 0, h / 2, -d / 2));
  g.add(box(0.08, h, d, color, w / 2, h / 2, 0), box(0.08, h, d, color, -w / 2, h / 2, 0));
  for (let i = 1; i < 5; i++) g.add(box(0.06, h * 0.7, 0.1, P.ink, -w / 2 + (i * w) / 5, h * 0.5, d / 2 + 0.03));
  const handle = new THREE.Mesh(new THREE.TorusGeometry(w * 0.4, 0.05, 4, 12, Math.PI), flat(P.ink));
  handle.position.y = h;
  g.add(handle);
  return g;
}

export function bowl(r = 1, color = "#d9e2ea") {
  const g = new THREE.Group();
  const geo = new THREE.SphereGeometry(r, 10, 6, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2);
  const m = new THREE.Mesh(geo, flat(color, { side: THREE.DoubleSide }));
  m.position.y = r;
  m.castShadow = true;
  g.add(m);
  return g;
}

export function candle() {
  const g = new THREE.Group();
  g.add(cyl(0.06, 0.06, 0.4, 6, "#fff8e6", 0, 0.2, 0));
  const f = new THREE.Mesh(new THREE.ConeGeometry(0.04, 0.12, 5), glow("#ffb347"));
  f.position.y = 0.47;
  g.add(f);
  return g;
}

export function laptop(screen = P.cyan) {
  const g = new THREE.Group();
  g.add(box(0.9, 0.05, 0.6, "#3b4250", 0, 0.025, 0));
  const lid = pivot(0, 0.05, -0.3, box(0.9, 0.6, 0.04, "#3b4250", 0, 0.3, 0));
  const s = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.5), glow(screen));
  s.position.set(0, 0.3, 0.025);
  lid.add(s);
  lid.rotation.x = -0.25;
  g.add(lid);
  return g;
}

/** A sauna: benches, a stove with stones, a bucket, wood walls. Floor at 0, open toward +z. */
export function sauna(w = 7, h = 5, d = 5) {
  const g = new THREE.Group();
  g.add(box(w, 0.2, d, P.woodDark, 0, -0.1, 0));
  g.add(box(w, h, 0.2, P.sauna, 0, h / 2, -d / 2));
  g.add(box(0.2, h, d, P.sauna, -w / 2, h / 2, 0), box(0.2, h, d, P.sauna, w / 2, h / 2, 0));
  for (let i = 0; i < 9; i++) g.add(box(w, 0.04, 0.05, P.woodDark, 0, 0.5 + i * 0.5, -d / 2 + 0.12));
  // two benches, stepped
  g.add(box(w - 0.4, 0.18, 1.2, P.wood, 0, 1.4, -d / 2 + 0.8));
  g.add(box(w - 0.4, 1.4, 0.15, P.woodDark, 0, 0.7, -d / 2 + 1.4));
  g.add(box(w - 0.4, 0.18, 1.0, P.wood, 0, 0.75, -d / 2 + 1.9));
  // stove with stones
  const stove = new THREE.Group();
  stove.add(box(1.1, 1.3, 1.0, "#3a3a3e", 0, 0.65, 0));
  stove.add(box(0.5, 0.3, 0.05, glow("#ff7a2a"), 0, 0.45, 0.51));
  for (let i = 0; i < 9; i++) {
    const st = ico(0.18, 0, "#6d6a68", -0.32 + (i % 3) * 0.32, 1.42 + Math.floor(i / 3) * 0.08, -0.3 + Math.floor(i / 3) * 0.3);
    st.rotation.set(i, i * 2, i * 3);
    stove.add(st);
  }
  stove.position.set(w / 2 - 1.2, 0, -d / 2 + 1.0);
  g.add(stove);
  g.userData.stove = stove;
  const bucket = new THREE.Group();
  bucket.add(cyl(0.26, 0.2, 0.4, 8, P.wood, 0, 0.2, 0));
  bucket.position.set(w / 2 - 2.3, 0, -d / 2 + 2.6);
  g.add(bucket);
  return g;
}

/** A red barn with a white trim and a drive-through window on the front (+z). */
export function barn(w = 8, h = 5, d = 6) {
  const g = new THREE.Group();
  g.add(box(w, h, d, P.barn, 0, h / 2, 0));
  const roof = new THREE.Mesh(new THREE.CylinderGeometry(0.01, w * 0.62, 2.6, 4, 1), flat("#5a2a26"));
  roof.rotation.y = Math.PI / 4;
  roof.scale.set(1, 1, d / w);
  roof.position.y = h + 1.3;
  g.add(roof);
  const trim = "#ffffff";
  g.add(box(w + 0.05, 0.2, 0.2, trim, 0, h, d / 2), box(0.2, h, 0.2, trim, w / 2, h / 2, d / 2), box(0.2, h, 0.2, trim, -w / 2, h / 2, d / 2));
  // big doors with the white X
  g.add(box(3, 3.4, 0.1, "#9e2623", -1.6, 1.7, d / 2 + 0.05));
  const x1 = box(0.18, 4.3, 0.06, trim, -1.6, 1.7, d / 2 + 0.11);
  x1.rotation.z = 0.72;
  const x2 = box(0.18, 4.3, 0.06, trim, -1.6, 1.7, d / 2 + 0.11);
  x2.rotation.z = -0.72;
  g.add(x1, x2);
  // drive-through window
  g.add(box(2.0, 1.6, 0.1, "#1b1b1f", 2.3, 2.2, d / 2 + 0.05));
  g.add(new THREE.Mesh(new THREE.PlaneGeometry(1.8, 1.4), glow("#ffe8b0")).translateX(2.3).translateY(2.2).translateZ(d / 2 + 0.11));
  g.add(box(2.4, 0.15, 0.7, trim, 2.3, 1.35, d / 2 + 0.3));
  return g;
}

/** A receipt strip (paper with lines); grow it with scale.y from its top. */
export function receipt(w = 0.6, h = 1.2) {
  const g = new THREE.Group();
  const paper = box(w, h, 0.02, "#ffffff", 0, -h / 2, 0);
  g.add(paper);
  for (let i = 0; i < 6; i++) g.add(box(w * (0.5 + (i % 3) * 0.12), 0.04, 0.03, "#666666", 0, -0.15 - i * (h / 7), 0.01));
  return g;
}

/** A glowing chain link (for the receipt chain over the barn). */
export function chainLink(color = P.yellow) {
  const m = new THREE.Mesh(new THREE.TorusGeometry(0.32, 0.08, 4, 8), glow(color));
  m.scale.set(1, 1.5, 1);
  return m;
}
