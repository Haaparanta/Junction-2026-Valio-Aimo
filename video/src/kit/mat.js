/** Cached flat-shaded materials and small geometry helpers shared by every view. */
import * as THREE from "three";

const lit = new Map();
const unlit = new Map();

/** Lit, flat-shaded Lambert. Cached by colour and options. */
export function flat(color, { opacity = 1, side = THREE.FrontSide, emissive = 0, emissiveIntensity = 1 } = {}) {
  const key = `${color}|${opacity}|${side}|${emissive}|${emissiveIntensity}`;
  if (!lit.has(key)) {
    const m = new THREE.MeshLambertMaterial({ color, flatShading: true, side, emissive, emissiveIntensity });
    if (opacity < 1) {
      m.transparent = true;
      m.opacity = opacity;
      m.depthWrite = false;
    }
    lit.set(key, m);
  }
  return lit.get(key);
}

/** Ignores light: neon, screens, glows. Fog off by default so signs stay bright. */
export function glow(color, { opacity = 1, additive = false, fog = false, side = THREE.FrontSide } = {}) {
  const key = `${color}|${opacity}|${additive}|${fog}|${side}`;
  if (!unlit.has(key)) {
    const m = new THREE.MeshBasicMaterial({ color, fog, side, toneMapped: false });
    if (opacity < 1 || additive) {
      m.transparent = true;
      m.opacity = opacity;
      m.depthWrite = false;
    }
    if (additive) m.blending = THREE.AdditiveBlending;
    unlit.set(key, m);
  }
  return unlit.get(key);
}

/** A material of its own (not cached), for things that fade or change colour over time. */
export const ownFlat = (color, opts = {}) => {
  const m = new THREE.MeshLambertMaterial({ color, flatShading: true, ...opts });
  if (opts.opacity !== undefined && opts.opacity < 1) m.transparent = true;
  return m;
};

const boxes = new Map();
export function boxGeo(w, h, d) {
  const key = `${w}|${h}|${d}`;
  if (!boxes.has(key)) boxes.set(key, new THREE.BoxGeometry(w, h, d));
  return boxes.get(key);
}

/** A box mesh that casts and receives shadows; y is the box centre. */
export function box(w, h, d, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(boxGeo(w, h, d), typeof material === "string" ? flat(material) : material);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

export function cyl(rt, rb, h, seg, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(
    new THREE.CylinderGeometry(rt, rb, h, seg),
    typeof material === "string" ? flat(material) : material,
  );
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

export function ico(r, detail, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(
    new THREE.IcosahedronGeometry(r, detail),
    typeof material === "string" ? flat(material) : material,
  );
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/** A pivot group at (x, y, z) holding children; rotate the pivot to swing them. */
export function pivot(x = 0, y = 0, z = 0, ...children) {
  const g = new THREE.Group();
  g.position.set(x, y, z);
  for (const c of children) g.add(c);
  return g;
}

/** Shadows on for every mesh below root. */
export function shadows(root, cast = true, receive = true) {
  root.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = cast;
      o.receiveShadow = receive;
    }
  });
  return root;
}
