/**
 * Hook (MrBeast style): the first sentence is the stakes, the first shot is the thumbnail.
 *
 * Beats (local s):
 * 0.00  wide (the thumbnail): the host points at Mansikki on her pedestal; "THIS COW HAS A" pops word by word
 * 0.50  snap zoom on the host, mid-shout
 * 0.82  whip pan to Mansikki
 * 0.98  "€500 LIMIT" slams; the red tag on her bell swings
 * 2.00  "LET'S BREAK IT." slams; confetti cannons fire; flash
 * 2.45  Mansikki: alarmed moo; shake
 */
import * as THREE from "three";
import { makeCow } from "../kit/cow.js";
import { bump, E, ease, pop, seg, track } from "../kit/ease.js";
import { burst, flash, glowSprite, shake, speedLines } from "../kit/fx.js";
import { box, cyl, glow } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { makePerson, mixPose, POSES } from "../kit/person.js";
import { noise1 } from "../kit/rand.js";
import { look, stage } from "../kit/stage.js";
import { outlined } from "../kit/text2d.js";
import { label, lights, neon } from "../kit/world.js";

const B = { words: [0.05, 0.2, 0.35, 0.48], host: 0.5, whip: 0.82, cow: 1.0, limit: 0.98, punch: 2.0, moo: 2.45 };

export function sounds() {
  return [
    { music: "hype", from: 0, rests: [[1.9, 2.0]] },
    { at: 0.0, sound: "boom", gain: 0.7 },
    { at: 0.02, voice: "hook-host", rate: 1.18 },
    { at: B.whip, sound: "whoosh", gain: 0.8 },
    { at: B.limit, sound: "slam", gain: 0.9 },
    { at: B.punch, sound: "confetti", gain: 0.8 },
    { at: B.punch, sound: "boom", gain: 0.9 },
    { at: B.moo, moo: "alarmed", gain: 0.9 },
  ];
}

const POINT_L = { shL: [-1.45, 0, -0.1], elL: [-0.1, 0, 0], shR: [0, 0, -0.5], elR: [-0.6, 0, 0], spine: [0, 0.2, 0] };

export function build(segment) {
  const { scene, camera } = stage({ background: "#0e1024", fog: ["#0e1024", 18, 40] });
  lights(scene, { dir: [-4, 9, 7], color: "#ffe2c4", intensity: 1.6, sky: "#6f7dff", groundColor: "#20183a", hemi: 0.7, ambient: 0.2 });

  scene.add(box(40, 0.2, 40, "#1d2240", 0, -0.1, 0));
  // a wall of milk crates
  for (let i = 0; i < 12; i++) {
    for (let k = 0; k < 5; k++) {
      const c = (i + k) % 3 === 0 ? P.blue : (i + k) % 3 === 1 ? P.yellow : "#ffffff";
      scene.add(box(1.25, 0.95, 1.0, c, -7.2 + i * 1.3, 0.5 + k * 1.0, -8 + (k % 2) * 0.1));
    }
  }
  const sign = neon("€500", P.red, { w: 3.6, h: 1.4 });
  sign.position.set(-3.6, 3.9, -6.9);
  scene.add(sign);
  const signGlow = glowSprite(P.red, 8, 0.6);
  signGlow.position.set(-3.6, 3.9, -6.7);
  scene.add(signGlow);

  // pedestal + spotlight
  scene.add(cyl(1.5, 1.7, 0.8, 12, "#ffffff", 1.6, 0.4, -1));
  scene.add(cyl(1.52, 1.52, 0.14, 12, P.pink, 1.6, 0.72, -1));
  const spot = new THREE.SpotLight("#fff4dc", 60, 14, 0.42, 0.5, 1.5);
  spot.position.set(1.6, 9, 0);
  spot.target.position.set(1.6, 0.8, -1);
  scene.add(spot, spot.target);
  const beam = new THREE.Mesh(new THREE.ConeGeometry(1.9, 8.5, 20, 1, true), glow("#fff4dc", { opacity: 0.08, additive: true, side: THREE.DoubleSide }));
  beam.position.set(1.6, 4.9, -1);
  scene.add(beam);

  const cow = makeCow();
  cow.root.position.set(1.6, 0.8, -1);
  scene.add(cow.root);
  // the €500 tag on her bell
  const tag = new THREE.Group();
  const tagBoard = label("€500", { w: 0.7, h: 0.4, color: "#ffffff", bg: P.red, px: 300 });
  tagBoard.position.y = -0.3;
  tag.add(tagBoard);
  tag.position.set(0, -0.3, 0.52);
  cow.j.neck.add(tag);

  // cannons
  for (const x of [-0.4, 3.6]) {
    const c = cyl(0.25, 0.32, 1.0, 8, "#444a5a", x, 0.5, -0.6);
    c.rotation.z = x < 1 ? -0.25 : 0.25;
    scene.add(c);
  }
  const confetti = [-0.4, 3.6].map((x, n) =>
    burst({
      count: 70,
      seed: `confetti${n}`,
      origin: [x, 1.1, -0.6],
      at: B.punch,
      speed: [7, 12],
      dir: [n === 0 ? 0.3 : -0.3, 1, -0.2],
      spread: 0.45,
      gravity: 6,
      floor: 0.02,
      spin: 9,
      make: (i, r) => new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.24), glow(r.pick([P.yellow, P.pink, P.cyan, P.lime, "#ffffff", "#3fbf5f"]), { side: THREE.DoubleSide, fog: true })),
    }),
  );
  for (const c of confetti) scene.add(c.object);

  // the host
  const host = makePerson({ shirt: "#29a8ff", hoodie: "#29a8ff", pants: "#22252e", hair: "short", hairColor: P.hair.brown, skin: P.skin[1] });
  host.root.position.set(-1.2, 0, 1.4);
  host.root.rotation.y = 0.45;
  scene.add(host.root);

  const camWide = track([[0, [0.7, 3.4, 11.0]], [B.host, [0.55, 3.15, 9.4], "outCubic"]]);
  const camHost = track([[B.host, [-0.6, 2.65, 6.0]], [B.whip, [-0.75, 2.6, 5.1], "outQuart"]]);
  const camCow = track([[B.cow, [1.7, 3.0, 7.6]], [2.3, [1.65, 3.05, 6.5], "outCubic"], [3.2, [1.65, 3.05, 6.2], "linear"]]);

  return {
    scene,
    camera,
    update(t) {
      // camera
      const sh = shake(t, B.limit, { amp: 0.12, dur: 0.3, seed: 2 }).map((v, i) => v + shake(t, B.moo, { amp: 0.18, dur: 0.5, seed: 5 })[i]);
      if (t < B.host) {
        look(camera, camWide(t), [0.35, 2.4, 0], { shake: sh });
      } else if (t < B.whip) {
        look(camera, camHost(t), [-1.15, 2.3, 1.4], { shake: sh });
      } else if (t < B.cow) {
        const k = E.inOutCubic(seg(t, B.whip, B.cow));
        const pos = [-0.75 + (1.7 + 0.75) * k, 2.6 + 0.4 * k, 5.1 + 2.5 * k];
        const tgt = [-1.15 + 2.75 * k, 2.3 + 0.05 * k, 1.4 - 2.4 * k];
        look(camera, pos, tgt, { roll: Math.sin(k * Math.PI) * 0.12 });
      } else {
        look(camera, camCow(t), [1.6, 2.4, -1], { shake: sh });
      }

      // host shouts with arms wide, leaning in
      host.pose(t < B.host ? POINT_L : mixPose(POINT_L, POSES.wide, ease(t, B.host, B.host + 0.15)));
      host.talk(Math.max(0, noise1(t * 14, 3) * 0.5 + 0.5) * (t < 2.9 ? 1 : 0));
      host.brows(0.25, 0.04);
      host.j.spine.rotation.x += 0.15 * bump(t, 0, 0.6);

      // the cow: breathing, tag swing, alarmed moo
      const m = bump(t, B.moo, B.moo + 0.6);
      cow.pose(mixPose(POSES.idle, POSES.wide, m * 0.7));
      cow.moo(m);
      cow.eyes(1 + 0.5 * seg(t, B.moo, B.moo + 0.1));
      cow.brows(-0.3 * seg(t, B.moo, B.moo + 0.1), 0.08 * seg(t, B.moo, B.moo + 0.1));
      cow.wag(t);
      cow.blink(t > 0.8 && t < 0.9 ? 1 : 0);
      cow.root.position.y = 0.8 + 0.02 * Math.sin(t * 3);
      const swing = t > B.limit ? Math.sin((t - B.limit) * 11) * 0.6 * Math.exp(-(t - B.limit) * 2.5) : 0;
      tag.rotation.z = swing;
      tag.scale.setScalar(1 + 0.5 * bump(t, B.limit, B.limit + 0.3));

      sign.scale.setScalar(1 + 0.08 * bump(t, B.limit, B.limit + 0.25));
      signGlow.material.opacity = 0.5 + 0.3 * bump(t, B.limit, B.limit + 0.3) + 0.05 * Math.sin(t * 20);
      for (const c of confetti) c.update(t);
    },
    overlay(g, t) {
      speedLines(g, t, bump(t, B.whip - 0.05, B.cow + 0.1), { cx: 540, cy: 860 });
      flash(g, 0.7 * (1 - seg(t, B.punch, B.punch + 0.2)) * (t >= B.punch ? 1 : 0));
      const words = segment.text.top.split(" ");
      // word by word, each one pops
      const size = 92;
      g.save();
      g.font = `${size}px 'Archivo Black', sans-serif`;
      const widths = words.map((w) => g.measureText(`${w} `).width);
      g.restore();
      const total = widths.reduce((a, b) => a + b, 0);
      let x = 540 - total / 2;
      words.forEach((w, i) => {
        const k = pop(t, B.words[i], 0.22);
        outlined(g, w, x + widths[i] / 2 - size * 0.12, 1180, { size, scale: k, fill: "#ffffff" });
        x += widths[i];
      });
      const lk = pop(t, B.limit, 0.25);
      outlined(g, segment.text.limit, 540, 1325, { size: 168, scale: lk * (1 + 0.15 * bump(t, B.limit, B.limit + 0.2)), fill: P.red, lw: 28, rot: -0.03 });
      const pk = pop(t, B.punch, 0.22);
      outlined(g, segment.text.punch, 540, 1460, { size: 112, scale: pk, fill: P.yellow, rot: 0.04, lw: 22 });
    },
  };
}
