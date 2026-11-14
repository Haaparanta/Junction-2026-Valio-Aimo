/** Space: a spiral galaxy of milk that swirls into place, by formula. */
import * as THREE from "three";
import { E, seg } from "./ease.js";
import { roundDot } from "./fx.js";
import { rng } from "./rand.js";

/**
 * N particles in `arms` spiral arms of radius R. update(t, form) places each one between its start in a
 * milk stream (below, at `from`) and its place in the spiral; form is 0..1, and the galaxy turns with t.
 */
export function makeGalaxy({ N = 5000, R = 14, arms = 3, seed = "galaxy", from = [0, -40, 0], size = 0.32 } = {}) {
  const r = rng(seed);
  const target = new Float32Array(N * 3);
  const start = new Float32Array(N * 3);
  const delay = new Float32Array(N);
  const colors = new Float32Array(N * 3);
  const palette = [new THREE.Color("#ffffff"), new THREE.Color("#fff4dc"), new THREE.Color("#cfe4ff"), new THREE.Color("#ffc4d8")];
  for (let i = 0; i < N; i++) {
    const rad = R * Math.pow(r.next(), 0.7);
    const arm = i % arms;
    const ang = (arm * 2 * Math.PI) / arms + rad * 0.32 + r.float(-0.35, 0.35) * (1.2 - rad / R);
    target[i * 3] = Math.cos(ang) * rad;
    target[i * 3 + 1] = r.float(-0.4, 0.4) * (1 - rad / R) * 2;
    target[i * 3 + 2] = Math.sin(ang) * rad;
    start[i * 3] = from[0] + r.float(-0.6, 0.6);
    start[i * 3 + 1] = from[1] + r.float(0, 20);
    start[i * 3 + 2] = from[2] + r.float(-0.6, 0.6);
    delay[i] = r.float(0, 0.5) + (rad / R) * 0.4;
    const c = rad < R * 0.15 ? palette[1] : palette[r.int(0, 3)];
    colors.set([c.r, c.g, c.b], i * 3);
  }
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(N * 3);
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const points = new THREE.Points(
    geo,
    new THREE.PointsMaterial({ size, map: roundDot(), vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }),
  );
  points.frustumCulled = false;
  const group = new THREE.Group();
  group.add(points);
  return {
    object: group,
    update(t, form = 1) {
      const spin = t * 0.25;
      const cs = Math.cos(spin);
      const sn = Math.sin(spin);
      for (let i = 0; i < N; i++) {
        const k = E.inOutCubic(seg(form * 1.9 - delay[i], 0, 1));
        // the stream swirls in: the angle lags while it travels
        const lag = (1 - k) * 2.5;
        const tx = target[i * 3] * Math.cos(lag) - target[i * 3 + 2] * Math.sin(lag);
        const tz = target[i * 3] * Math.sin(lag) + target[i * 3 + 2] * Math.cos(lag);
        const x = start[i * 3] + (tx - start[i * 3]) * k;
        const y = start[i * 3 + 1] + (target[i * 3 + 1] - start[i * 3 + 1]) * k;
        const z = start[i * 3 + 2] + (tz - start[i * 3 + 2]) * k;
        pos[i * 3] = x * cs - z * sn;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = x * sn + z * cs;
      }
      geo.attributes.position.needsUpdate = true;
    },
  };
}
