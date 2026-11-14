/**
 * A blocky person: box head and torso, two-part arms and legs on pivots, black box eyes.
 * Feet at y = 0, about 2.5 units tall, facing +z. The character's right side is -x.
 *
 * Joints (shared with the cow and the robot): spine, neck, shL, elL, shR, elR, hipL, hipR.
 * Rotations are Euler XYZ in radians: shoulder x < 0 swings the arm forward, shL z > 0 lifts the
 * left arm out to the side (shR z < 0 the right), elbow x < 0 bends the forearm forward, neck x > 0 looks down.
 */
import * as THREE from "three";
import { P } from "./palette.js";
import { box, cyl, flat, glow, pivot } from "./mat.js";

export const POSES = {
  idle: { shL: [0, 0, 0.08], shR: [0, 0, -0.08], elL: [-0.15, 0, 0], elR: [-0.15, 0, 0] },
  phone: { shL: [0, 0, 0.08], elL: [-0.15, 0, 0], shR: [-0.55, 0, 0.25], elR: [-1.95, 0, 0], neck: [0.05, 0, 0] },
  phoneLow: { shL: [0, 0, 0.08], elL: [-0.15, 0, 0], shR: [-0.35, 0, 0.2], elR: [-1.35, 0, 0], neck: [0.35, 0, 0] },
  phoneBoth: { shL: [-0.35, 0, -0.2], elL: [-1.3, 0, 0], shR: [-0.35, 0, 0.2], elR: [-1.3, 0, 0], neck: [0.35, 0, 0] },
  armsUp: { shL: [0, 0, 2.7], shR: [0, 0, -2.7], elL: [0, 0, 0.2], elR: [0, 0, -0.2], spine: [-0.08, 0, 0] },
  wide: { shL: [0, 0, 1.25], shR: [0, 0, -1.25], elL: [0, 0, 0.3], elR: [0, 0, -0.3], spine: [-0.1, 0, 0] },
  point: { shL: [0, 0, 0.1], elL: [-0.2, 0, 0], shR: [-1.5, 0, 0.05], elR: [0, 0, 0] },
  tap: { shL: [0, 0, 0.1], elL: [-0.2, 0, 0], shR: [-1.15, 0, 0.1], elR: [-0.4, 0, 0] },
  hold: { shL: [-1.1, 0, -0.12], elL: [-0.45, 0, 0], shR: [-1.1, 0, 0.12], elR: [-0.45, 0, 0] },
  holdUp: { shL: [-2.3, 0, -0.1], elL: [-0.3, 0, 0], shR: [-2.3, 0, 0.1], elR: [-0.3, 0, 0], neck: [-0.25, 0, 0] },
  sixSeven: { shL: [-0.55, 0, 0.12], elL: [-1.05, 0, 0], shR: [-0.55, 0, -0.12], elR: [-1.05, 0, 0] },
  bicepHeart: {
    shL: [0, 0, 1.45],
    elL: [-0.25, 0, 1.9],
    shR: [-1.15, -0.55, 0.3],
    elR: [-1.25, 0, 0],
    neck: [0, 0.35, 0.08],
    spine: [0, 0.25, 0],
  },
  shrug: { shL: [0, 0, 0.55], elL: [-1.3, 0, 0.4], shR: [0, 0, -0.55], elR: [-1.3, 0, -0.4], neck: [0, 0, 0.15] },
  lean: { spine: [0.35, 0, 0], neck: [-0.25, 0, 0], shL: [-0.4, 0, 0.1], shR: [-0.55, 0, 0.25], elR: [-1.9, 0, 0] },
  flail: {
    shL: [0, 0, 2.4],
    shR: [0, 0, -2.0],
    elL: [0, 0, 0.6],
    elR: [0, 0, -0.9],
    hipL: [0.5, 0, 0.35],
    hipR: [-0.7, 0, -0.3],
  },
  sit: {
    hipL: [-1.5, 0, 0.05],
    hipR: [-1.5, 0, -0.05],
    kneeL: [1.5, 0, 0],
    kneeR: [1.5, 0, 0],
    shL: [-0.3, 0, 0.1],
    shR: [-0.3, 0, -0.1],
    elL: [-0.6, 0, 0],
    elR: [-0.6, 0, 0],
  },
};

const JOINTS = ["spine", "neck", "shL", "elL", "shR", "elR", "hipL", "hipR", "kneeL", "kneeR"];

/** Linear mix of two poses (objects of joint → [x, y, z]). */
export function mixPose(a, b, k) {
  const out = {};
  for (const j of JOINTS) {
    const p = a[j] ?? [0, 0, 0];
    const q = b[j] ?? [0, 0, 0];
    out[j] = [p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k, p[2] + (q[2] - p[2]) * k];
  }
  return out;
}

/** Adds offsets to a pose: add(pose, { shL: [0.2, 0, 0] }). */
export function addPose(pose, extra) {
  const out = { ...pose };
  for (const [j, v] of Object.entries(extra)) {
    const p = out[j] ?? [0, 0, 0];
    out[j] = [p[0] + v[0], p[1] + v[1], p[2] + v[2]];
  }
  return out;
}

export function applyPose(j, pose) {
  for (const name of JOINTS) {
    if (!j[name]) continue;
    const r = pose[name] ?? [0, 0, 0];
    j[name].rotation.set(r[0], r[1], r[2]);
  }
}

/** The 6-7 hands at time t: palms up, going up and down in turn. */
export function sixSevenPose(t, speed = 7) {
  const s = Math.sin(t * speed);
  return addPose(POSES.sixSeven, { shL: [-0.35 * s, 0, 0], shR: [0.35 * s, 0, 0], elL: [-0.3 * s, 0, 0], elR: [0.3 * s, 0, 0] });
}

/**
 * opts: skin, shirt, pants, shoes, hair ('short' | 'long' | 'mullet' | 'bun' | 'ponytail' | 'spiky' | 'bald'),
 * hairColor, beanie, cap, chefHat, sunglasses, glasses, chain, tank, hoodie, overalls, patches, towel,
 * tired, mustache, beard, headset, scale.
 */
export function makePerson(opts = {}) {
  const o = {
    skin: P.skin[0],
    shirt: P.blue,
    pants: "#2b3445",
    shoes: "#1d1d1f",
    hair: "short",
    hairColor: P.hair.brown,
    ...opts,
  };
  const root = new THREE.Group();
  const skinM = flat(o.skin);
  const bare = o.towel; // sauna: no shirt
  const torsoColor = bare ? o.skin : o.tank ? o.skin : o.shirt;
  const sleeve = bare || o.tank ? o.skin : o.shirt;
  const legColor = o.overalls ?? o.pants;

  // legs
  const legs = {};
  for (const [side, x] of [["L", 0.24], ["R", -0.24]]) {
    const knee = pivot(0, -0.5, 0, box(0.34, 0.5, 0.36, legColor, 0, -0.25, 0), box(0.38, 0.17, 0.5, o.shoes, 0, -0.47, 0.06));
    const hip = pivot(x, 1.0, 0, box(0.36, 0.52, 0.38, legColor, 0, -0.25, 0), knee);
    legs[side] = { hip, knee };
    root.add(hip);
    if (o.patches) {
      const colors = [P.yellow, P.lime, P.pink, P.cyan, P.orange, P.red];
      for (let i = 0; i < 3; i++) {
        const c = colors[(i * 2 + (side === "L" ? 1 : 0)) % colors.length];
        knee.add(box(0.14, 0.12, 0.02, c, (i - 1) * 0.08, -0.12 - i * 0.09, 0.19));
      }
    }
  }
  root.add(box(0.86, 0.26, 0.46, legColor, 0, 1.05, 0));

  // torso
  const spine = pivot(0, 1.0, 0);
  root.add(spine);
  const torso = box(0.92, 0.95, 0.52, torsoColor, 0, 0.56, 0);
  spine.add(torso);
  if (o.tank) {
    spine.add(box(0.72, 0.9, 0.54, o.tank, 0, 0.53, 0));
  }
  if (o.overalls) {
    // student overalls: top half tied around the waist, sleeves knotted in front
    spine.add(box(0.98, 0.24, 0.58, o.overalls, 0, 0.12, 0));
    spine.add(box(0.2, 0.34, 0.08, o.overalls, -0.08, 0.02, 0.31));
    spine.add(box(0.2, 0.34, 0.08, o.overalls, 0.1, -0.02, 0.31));
  }
  if (o.towel) root.add(box(0.96, 0.5, 0.56, "#ffffff", 0, 1.0, 0));
  if (o.puffer) {
    for (let i = 0; i < 3; i++) spine.add(box(1.0, 0.24, 0.6, o.puffer, 0, 0.25 + i * 0.3, 0));
  }
  if (o.hoodie) {
    spine.add(box(0.7, 0.3, 0.3, o.hoodie, 0, 1.0, -0.28)); // hood behind the neck
    spine.add(box(0.04, 0.26, 0.03, "#ffffff", -0.12, 0.82, 0.27));
    spine.add(box(0.04, 0.26, 0.03, "#ffffff", 0.12, 0.82, 0.27));
    spine.add(box(0.5, 0.2, 0.04, o.hoodie, 0, 0.33, 0.27)); // pocket
  }
  if (o.chain) {
    const chain = new THREE.Mesh(new THREE.TorusGeometry(0.24, 0.035, 4, 10), flat("#ffcc33"));
    chain.position.set(0, 0.96, 0.2);
    chain.rotation.x = 1.2;
    spine.add(chain);
  }

  // head
  const neck = pivot(0, 1.04, 0);
  spine.add(neck);
  const headSize = 0.78;
  const head = box(headSize, headSize, headSize, skinM, 0, 0.42, 0);
  neck.add(head);
  const fz = headSize / 2 + 0.012;
  const eyeL = box(0.11, 0.16, 0.03, P.ink, 0.17, 0.48, fz);
  const eyeR = box(0.11, 0.16, 0.03, P.ink, -0.17, 0.48, fz);
  neck.add(eyeL, eyeR);
  const browL = box(0.2, 0.05, 0.03, o.hairColor === P.hair.blond ? "#9c7a3c" : P.ink, 0.17, 0.64, fz);
  const browR = box(0.2, 0.05, 0.03, o.hairColor === P.hair.blond ? "#9c7a3c" : P.ink, -0.17, 0.64, fz);
  neck.add(browL, browR);
  const mouth = box(0.22, 0.06, 0.03, "#5a1f1f", 0, 0.24, fz);
  neck.add(mouth);
  if (o.tired) {
    neck.add(box(0.14, 0.05, 0.02, "#8a5a7a", 0.17, 0.37, fz), box(0.14, 0.05, 0.02, "#8a5a7a", -0.17, 0.37, fz));
  }
  if (o.mustache) neck.add(box(0.32, 0.07, 0.05, o.hairColor, 0, 0.31, fz + 0.01));
  if (o.beard) neck.add(box(0.8, 0.28, 0.2, o.hairColor, 0, 0.1, 0.32));
  let shades = null;
  if (o.sunglasses) {
    shades = box(0.62, 0.15, 0.04, P.ink, 0, 0.5, fz + 0.02);
    shades.add(box(0.14, 0.05, 0.04, "#ffffff", 0.2, 0.03, 0.025));
    neck.add(shades);
  }
  if (o.glasses) {
    for (const x of [0.17, -0.17]) {
      neck.add(box(0.22, 0.03, 0.03, P.ink, x, 0.58, fz + 0.02), box(0.22, 0.03, 0.03, P.ink, x, 0.38, fz + 0.02));
      neck.add(box(0.03, 0.2, 0.03, P.ink, x + 0.1, 0.48, fz + 0.02), box(0.03, 0.2, 0.03, P.ink, x - 0.1, 0.48, fz + 0.02));
    }
  }

  // hair and hats
  const hc = o.hairColor;
  const top = 0.42 + headSize / 2;
  if (o.hair !== "bald" && !o.chefHat) {
    neck.add(box(0.84, 0.18, 0.84, hc, 0, top + 0.06, -0.01));
    neck.add(box(0.84, 0.42, 0.18, hc, 0, top - 0.18, -0.34));
    if (o.hair === "short" || o.hair === "spiky") {
      neck.add(box(0.84, 0.14, 0.16, hc, 0, top - 0.04, 0.36)); // fringe
    }
    if (o.hair === "spiky") {
      for (let i = 0; i < 5; i++) {
        const c = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.3, 4), flat(hc));
        c.position.set(-0.3 + i * 0.15, top + 0.25, -0.05 + (i % 2) * 0.1);
        c.rotation.z = (i - 2) * 0.15;
        neck.add(c);
      }
    }
    if (o.hair === "long" || o.hair === "mullet") {
      neck.add(box(0.86, 0.75, 0.2, hc, 0, top - 0.55, -0.36));
      if (o.hair === "long") {
        neck.add(box(0.12, 0.7, 0.6, hc, 0.43, top - 0.42, -0.1), box(0.12, 0.7, 0.6, hc, -0.43, top - 0.42, -0.1));
        neck.add(box(0.84, 0.14, 0.14, hc, 0, top - 0.04, 0.37));
      }
    }
    if (o.hair === "bun") neck.add(box(0.32, 0.3, 0.32, hc, 0, top + 0.28, -0.12));
    if (o.hair === "ponytail") neck.add(box(0.2, 0.6, 0.2, hc, 0, top - 0.25, -0.5));
  }
  if (o.beanie) {
    neck.add(box(0.88, 0.32, 0.88, o.beanie, 0, top + 0.1, 0));
    neck.add(box(0.9, 0.1, 0.9, "#ffffff", 0, top - 0.05, 0));
    neck.add(box(0.2, 0.2, 0.2, "#ffffff", 0, top + 0.35, 0));
  }
  if (o.cap) {
    neck.add(box(0.86, 0.22, 0.86, o.cap, 0, top + 0.08, 0));
    neck.add(box(0.7, 0.05, 0.4, o.cap, 0, top - 0.02, 0.58));
  }
  if (o.chefHat) {
    neck.add(cyl(0.38, 0.36, 0.55, 8, "#ffffff", 0, top + 0.3, 0));
    neck.add(cyl(0.48, 0.42, 0.2, 8, "#ffffff", 0, top + 0.62, 0));
  }
  if (o.headset) {
    neck.add(box(0.9, 0.06, 0.1, P.ink, 0, top + 0.06, 0));
    neck.add(box(0.08, 0.3, 0.26, P.ink, 0.43, 0.45, 0), box(0.08, 0.3, 0.26, P.ink, -0.43, 0.45, 0));
    neck.add(box(0.04, 0.04, 0.4, P.ink, 0.44, 0.3, 0.22));
  }

  // arms
  const arms = {};
  for (const [side, x] of [["L", 0.6], ["R", -0.6]]) {
    const hand = box(0.27, 0.2, 0.28, skinM, 0, -0.55, 0);
    const el = pivot(0, -0.52, 0, box(0.26, 0.46, 0.28, sleeve, 0, -0.22, 0), hand);
    const sh = pivot(x, 0.86, 0, box(0.28, 0.54, 0.3, sleeve, 0, -0.25, 0), el);
    if (o.puffer) sh.add(box(0.36, 0.5, 0.38, o.puffer, 0, -0.24, 0));
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
  if (o.scale) root.scale.setScalar(o.scale);

  const api = {
    root,
    j,
    head,
    handL: arms.L.hand,
    handR: arms.R.hand,
    face: { eyeL, eyeR, mouth, browL, browR },
    shades,
    pose(p) {
      applyPose(j, p);
      return api;
    },
    /** 0 closed … 1 wide open */
    talk(k) {
      mouth.scale.set(1 - 0.25 * k, 1 + 4 * k, 1);
      return api;
    },
    /** 0 open … 1 shut */
    blink(k) {
      eyeL.scale.y = eyeR.scale.y = Math.max(0.08, 1 - k);
      return api;
    },
    /** Eye size for surprise: 1 normal. */
    eyes(s) {
      eyeL.scale.set(s, s, 1);
      eyeR.scale.set(s, s, 1);
      return api;
    },
    /** Brow tilt: > 0 angry (inner ends down), < 0 worried; lift raises them. */
    brows(tilt, lift = 0) {
      browL.rotation.z = tilt;
      browR.rotation.z = -tilt;
      browL.position.y = browR.position.y = 0.64 + lift;
      return api;
    },
    /** Puts a mesh in a hand, at the palm. */
    hold(mesh, side = "R", x = 0, y = -0.68, z = 0.1) {
      const hand = side === "R" ? arms.R.el : arms.L.el;
      mesh.position.set(x, y, z);
      hand.add(mesh);
      return mesh;
    },
  };
  api.pose(POSES.idle);
  return api;
}

/** A phone: black slab with a screen that ignores light. Screen faces +z of the phone. */
export function makePhone(screenColor = P.paper) {
  const g = new THREE.Group();
  g.add(box(0.3, 0.56, 0.05, P.ink));
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.26, 0.5), glow(screenColor));
  screen.position.z = 0.03;
  g.add(screen);
  g.userData.screen = screen;
  return g;
}
