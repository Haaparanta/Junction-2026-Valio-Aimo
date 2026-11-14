/**
 * Mansikki: a low-poly cow mascot on two legs, after the app's avatar (white with black patches, pink
 * muzzle, cream horns), in a call-centre headset. Same joints as the person (see person.js), plus a jaw
 * for moos and a tail. Feet at y = 0, about 3 units tall, facing +z.
 */
import * as THREE from "three";
import { P } from "./palette.js";
import { box, cyl, flat, glow, pivot } from "./mat.js";
import { applyPose, POSES } from "./person.js";

export function makeCow({ bell = true, headset = true, scale = 1 } = {}) {
  const root = new THREE.Group();
  const white = flat("#ffffff");
  const spot = flat(P.ink);
  const hoof = flat("#3a3030");

  // legs
  const legs = {};
  for (const [side, x] of [["L", 0.3], ["R", -0.3]]) {
    const knee = pivot(0, -0.45, 0, box(0.42, 0.45, 0.44, white, 0, -0.22, 0), box(0.46, 0.18, 0.5, hoof, 0, -0.43, 0.02));
    const hip = pivot(x, 0.95, 0, box(0.44, 0.5, 0.46, white, 0, -0.23, 0), knee);
    if (side === "L") knee.add(box(0.2, 0.2, 0.02, spot, 0.05, -0.15, 0.23));
    legs[side] = { hip, knee };
    root.add(hip);
  }

  // body
  const spine = pivot(0, 0.95, 0);
  root.add(spine);
  spine.add(box(1.22, 1.25, 0.9, white, 0, 0.6, 0));
  // patches like the app's cow (black on white)
  spine.add(box(0.42, 0.38, 0.03, spot, 0.3, 0.86, 0.46));
  spine.add(box(0.28, 0.3, 0.03, spot, -0.38, 0.3, 0.46));
  spine.add(box(0.03, 0.5, 0.46, spot, 0.62, 0.6, -0.1));
  spine.add(box(0.03, 0.36, 0.3, spot, -0.62, 0.9, 0.15));
  spine.add(box(0.6, 0.45, 0.03, spot, -0.1, 0.7, -0.46));
  spine.add(box(0.5, 0.36, 0.04, P.muzzle, 0, 0.12, 0.45)); // belly patch
  // tail
  const tail = pivot(0, 0.25, -0.45, box(0.08, 0.7, 0.08, white, 0, -0.32, -0.02), box(0.16, 0.22, 0.16, spot, 0, -0.72, -0.02));
  tail.rotation.x = 0.5;
  spine.add(tail);

  // head
  const neck = pivot(0, 1.22, 0.05);
  spine.add(neck);
  if (bell) {
    neck.add(box(0.95, 0.1, 0.75, P.red, 0, 0.0, 0.05)); // collar
    const b = cyl(0.1, 0.16, 0.22, 6, P.yellow, 0, -0.12, 0.45);
    neck.add(b);
  }
  const head = new THREE.Group();
  head.position.y = 0.5;
  neck.add(head);
  head.add(box(0.98, 0.82, 0.86, white, 0, 0, 0));
  head.add(box(0.36, 0.34, 0.03, spot, -0.22, 0.12, 0.44)); // patch over the right eye, like the favicon
  head.add(box(0.3, 0.14, 0.4, spot, 0, 0.45, 0.12)); // tuft
  // muzzle: upper part fixed, jaw hinged for moos
  head.add(box(0.86, 0.3, 0.36, P.muzzle, 0, -0.18, 0.5));
  head.add(box(0.1, 0.12, 0.03, "#7a2b40", -0.18, -0.14, 0.69), box(0.1, 0.12, 0.03, "#7a2b40", 0.18, -0.14, 0.69));
  const jaw = pivot(0, -0.32, 0.36, box(0.78, 0.14, 0.38, P.muzzle, 0, -0.06, 0.15));
  jaw.add(box(0.6, 0.06, 0.3, "#7a2b40", 0, 0.02, 0.16)); // mouth inside, shows when open
  head.add(jaw);
  const eyeL = box(0.13, 0.17, 0.03, P.ink, 0.22, 0.12, 0.445);
  const eyeR = box(0.13, 0.17, 0.03, P.ink, -0.22, 0.12, 0.465);
  const glintL = box(0.04, 0.05, 0.02, "#ffffff", 0.25, 0.17, 0.46);
  const glintR = box(0.04, 0.05, 0.02, "#ffffff", -0.19, 0.17, 0.48);
  head.add(eyeL, eyeR, glintL, glintR);
  const browL = box(0.2, 0.05, 0.03, P.ink, 0.22, 0.3, 0.445);
  const browR = box(0.2, 0.05, 0.03, "#ffffff", -0.22, 0.3, 0.47);
  head.add(browL, browR);
  // horns and ears
  for (const s of [1, -1]) {
    const horn = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.36, 5), flat(P.horn));
    horn.position.set(0.32 * s, 0.55, 0);
    horn.rotation.z = -0.5 * s;
    horn.castShadow = true;
    head.add(horn);
    const ear = pivot(0.5 * s, 0.18, 0, box(0.36, 0.14, 0.22, white, 0.16 * s, 0, 0), box(0.24, 0.08, 0.02, P.muzzle, 0.17 * s, 0, 0.11));
    ear.rotation.z = -0.35 * s;
    head.add(ear);
  }
  let mic = null;
  if (headset) {
    head.add(box(1.06, 0.07, 0.12, P.ink, 0, 0.44, -0.05));
    head.add(box(0.1, 0.34, 0.3, P.ink, 0.53, 0.16, -0.05), box(0.1, 0.34, 0.3, P.ink, -0.53, 0.16, -0.05));
    const boom = box(0.04, 0.04, 0.62, P.ink, 0.5, -0.08, 0.27);
    boom.rotation.y = -0.45;
    head.add(boom);
    mic = new THREE.Mesh(new THREE.SphereGeometry(0.06, 6, 4), glow(P.lime));
    mic.position.set(0.36, -0.12, 0.56);
    head.add(mic);
  }

  // arms with hooves
  const arms = {};
  for (const [side, x] of [["L", 0.76], ["R", -0.76]]) {
    const hand = box(0.36, 0.2, 0.36, hoof, 0, -0.5, 0);
    const el = pivot(0, -0.48, 0, box(0.32, 0.42, 0.34, white, 0, -0.2, 0), hand);
    const sh = pivot(x, 1.05, 0, box(0.34, 0.5, 0.36, white, 0, -0.23, 0), el);
    if (side === "R") sh.add(box(0.02, 0.2, 0.2, spot, -0.18, -0.2, 0));
    spine.add(sh);
    arms[side] = { sh, el, hand };
  }

  const j = {
    spine,
    neck,
    shL: arms.L.sh,
    elL: arms.L.el,
    shR: arms.R.sh,
    elR: arms.R.el,
    hipL: legs.L.hip,
    hipR: legs.R.hip,
    kneeL: legs.L.knee,
    kneeR: legs.R.knee,
  };
  root.scale.setScalar(scale);

  const api = {
    root,
    j,
    head,
    jaw,
    tail,
    mic,
    face: { eyeL, eyeR, browL, browR },
    pose(p) {
      applyPose(j, p);
      return api;
    },
    /** A moo: 0 shut … 1 head up, jaw wide. */
    moo(k) {
      jaw.rotation.x = 0.6 * k;
      head.rotation.x = -0.3 * k;
      return api;
    },
    /** Chewing the cud: jaw side to side at phase p. */
    chew(p, k = 1) {
      jaw.rotation.x = (0.12 + 0.08 * Math.sin(p * 2)) * k;
      jaw.position.x = 0.07 * Math.sin(p) * k;
      return api;
    },
    eyes(s) {
      eyeL.scale.set(s, s, 1);
      eyeR.scale.set(s, s, 1);
      return api;
    },
    /** > 0 frown, < 0 worried; lift raises the brows (alarmed). */
    brows(tilt, lift = 0) {
      browL.rotation.z = tilt;
      browR.rotation.z = -tilt;
      browL.position.y = browR.position.y = 0.3 + lift;
      return api;
    },
    blink(k) {
      eyeL.scale.y = eyeR.scale.y = Math.max(0.08, 1 - k);
      glintL.visible = glintR.visible = k < 0.5;
      return api;
    },
    wag(t) {
      tail.rotation.z = 0.35 * Math.sin(t * 5);
      return api;
    },
    hold(mesh, side = "R", x = 0, y = -0.66, z = 0.12) {
      mesh.position.set(x, y, z);
      (side === "R" ? arms.R.el : arms.L.el).add(mesh);
      return mesh;
    },
  };
  api.pose(POSES.idle);
  return api;
}
