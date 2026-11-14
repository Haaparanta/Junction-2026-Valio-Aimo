/**
 * 400 L · MANSIKKAKAKKU: a chef names a dish; Mansikki plans its ingredients into the basket (about 40 s
 * in the real app, so the time skips). Mansikki means strawberry.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.90  the chef, arm up: "Mansikkakakku for forty!"
 * 2.45  Mansikki thinks: a progress ring fills over her head
 * 2.75  "40 SECONDS LATER" card
 * 3.15  Valio kuohukerma, maitorahka and voi, then strawberries, sugar and eggs rain into the basket (pops)
 * 4.20  the last strawberry bonks Mansikki on the head; the chef: "we're so back."
 */
import * as THREE from "three";
import { makeCow } from "../kit/cow.js";
import { bump, ease, pop, seg, track } from "../kit/ease.js";
import { drop, flash, shake } from "../kit/fx.js";
import { box, glow } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { makePerson, mixPose, POSES } from "../kit/person.js";
import { bag, basket, butter, carton, counter, egg, strawberry, tub } from "../kit/props.js";
import { noise1, rng } from "../kit/rand.js";
import { look, stage } from "../kit/stage.js";
import { boxCaption, caption, chip, outlined } from "../kit/text2d.js";
import { lights, room } from "../kit/world.js";

const B = { ask: 0.9, think: 2.45, later: 2.75, rain: 3.15, bonk: 4.2 };

export function sounds() {
  const r = rng("cake-pops");
  return [
    { music: "trap", from: 0.86, rests: [[2.45, 3.15]] },
    { at: B.ask, voice: "cake-chef", rate: 1.15 },
    { at: B.think, sound: "tick", gain: 0.4, dur: 0.3 },
    { at: B.later, sound: "whoosh", gain: 0.6 },
    { at: B.later + 0.05, sound: "slam", gain: 0.6 },
    ...Array.from({ length: 12 }, (_, i) => ({ at: B.rain + 0.2 + i * 0.09 + r.float(0, 0.03), sound: "pop", gain: 0.45 })),
    { at: B.bonk, sound: "bonk", gain: 0.8 },
    { at: B.bonk + 0.1, moo: "question", gain: 0.6 },
    { at: B.bonk + 0.1, voice: "cake-back", rate: 1.2 },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: "#dfe8ee", fog: ["#dfe8ee", 20, 40] });
  lights(scene, { dir: [4, 10, 7], color: "#ffffff", intensity: 2.0, sky: "#ffffff", groundColor: "#9aa5b1", hemi: 1.1, ambient: 0.3, box: 9 });
  const rm = room(14, 6.5, 16, { wall: P.tile, floor: "#b8c2cc", side: "#e4ebf0" });
  rm.position.z = 3;
  scene.add(rm);
  // tile grid on the back wall
  for (let i = 0; i < 22; i++) scene.add(box(0.03, 6.5, 0.02, "#c9d4dc", -7 + i * 0.66, 3.25, -4.88));
  for (let k = 0; k < 10; k++) scene.add(box(14, 0.03, 0.02, "#c9d4dc", 0, 0.66 * k, -4.88));
  const ct = counter(12, 1.2, 1.4);
  ct.position.set(0, 0, -3.9);
  scene.add(ct);
  for (let i = 0; i < 5; i++) {
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.5, 8), new THREE.MeshLambertMaterial({ color: "#aeb8c2", flatShading: true }));
    pot.position.set(-4 + i * 2, 1.65, -3.9);
    scene.add(pot);
  }

  const bk = basket(2.6, 1.8, 1.1, P.yellow);
  bk.position.set(0, 0, 0.3);
  scene.add(bk);

  // ingredients: they fall into the basket in order
  const r = rng("cake");
  const makers = [
    () => carton("KUOHUKERMA", { color: P.valio, s: 1.0 }),
    () => tub("MAITORAHKA", { body: "#ffffff", lid: P.valio, text: P.valio, s: 1.2 }),
    () => butter(1.1),
    () => carton("KUOHUKERMA", { color: P.valio, s: 1.0 }),
    () => tub("MAITORAHKA", { body: "#ffffff", lid: P.valio, text: P.valio, s: 1.2 }),
    () => strawberry(1.6),
    () => bag("SOKERI", "#ffffff"),
    () => strawberry(1.6),
    () => egg(1.6),
    () => strawberry(1.6),
    () => egg(1.6),
    () => butter(1.1),
  ];
  const items = makers.map((mk, i) => {
    const m = mk();
    m.position.set(r.float(-0.8, 0.8), 8, 0.3 + r.float(-0.4, 0.4));
    m.rotation.y = r.float(-0.5, 0.5);
    scene.add(m);
    return { m, at: B.rain + i * 0.09, y1: 0.15 + Math.floor(i / 4) * 0.28, spin: r.float(-4, 4) };
  });
  const bonker = strawberry(2.2);
  scene.add(bonker);

  const chef = makePerson({ shirt: "#ffffff", pants: "#2b2b2b", chefHat: true, mustache: true, hair: "short", hairColor: P.hair.black, skin: P.skin[1] });
  chef.root.position.set(-1.95, 0, 0.6);
  chef.root.rotation.y = 0.35;
  scene.add(chef.root);
  // buttons on the chef's jacket
  for (let i = 0; i < 3; i++) chef.j.spine.add(box(0.07, 0.07, 0.03, P.ink, 0.15, 0.3 + i * 0.22, 0.27));

  const cow = makeCow();
  cow.root.position.set(1.95, 0, 0.6);
  cow.root.rotation.y = -0.35;
  scene.add(cow.root);
  // progress ring over her head: segments light up
  const ring = new THREE.Group();
  const segs = [];
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2;
    const s = box(0.14, 0.26, 0.05, glow(P.pink), Math.sin(a) * 0.55, Math.cos(a) * 0.55, 0);
    s.rotation.z = -a;
    segs.push(s);
    ring.add(s);
  }
  ring.position.set(1.95, 3.95, 0.9);
  scene.add(ring);

  const cam = track([[0, [0, 4.0, 12.6]], [B.rain, [0, 3.9, 11.9], "linear"], [B.bonk, [0.2, 3.8, 11.2], "linear"], [B.bonk + 0.2, [0.8, 3.4, 9.0], "outQuart"], [5.6, [0.8, 3.4, 8.7], "linear"]]);
  const tgt = track([[0, [0, 1.75, 0]], [B.bonk, [0.1, 1.8, 0.3]], [B.bonk + 0.2, [0.6, 2.0, 0.4], "outQuart"]]);

  return {
    scene,
    camera,
    update(t) {
      look(camera, cam(t), tgt(t), { shake: shake(t, B.bonk, { amp: 0.08, dur: 0.3, seed: 9 }) });
      // the chef announces, then celebrates
      const back = ease(t, B.bonk + 0.1, B.bonk + 0.3);
      chef.pose(mixPose(mixPose(POSES.idle, { ...POSES.wide, shR: [0, 0, -2.6], elR: [0, 0, -0.2] }, bump(t, B.ask - 0.1, B.ask + 1.3)), POSES.armsUp, back));
      chef.talk((t > B.ask && t < B.ask + 1.5) || (t > B.bonk + 0.1 && t < B.bonk + 1.2) ? Math.max(0, noise1(t * 12, 5) * 0.5 + 0.4) : 0);
      chef.root.position.y = 0.1 * Math.abs(Math.sin(t * 8)) * back;
      // Mansikki thinks, then gets bonked
      const thinking = t > B.think && t < B.rain;
      ring.visible = thinking;
      const fill = seg(t, B.think, B.later);
      segs.forEach((s, i) => (s.visible = i / 16 < fill));
      ring.rotation.z = -t * 2;
      cow.pose(thinking ? { ...POSES.idle, shR: [-2.0, 0, 0.4], elR: [-1.6, 0, 0] } : POSES.idle);
      cow.head.rotation.z = thinking ? 0.15 : 0;
      const bonk = drop(t, B.bonk - 0.4, 9, 3.05, 30, 0.35);
      bonker.visible = t > B.bonk - 0.4;
      bonker.position.set(1.95, bonk.y, 0.7);
      bonker.rotation.z = bonk.landed ? 0.4 : 0;
      cow.eyes(1 + 0.4 * bump(t, B.bonk, B.bonk + 0.4));
      cow.blink(bump(t, B.bonk, B.bonk + 0.15));
      cow.root.scale.y = 1 - 0.08 * bump(t, B.bonk, B.bonk + 0.2);
      cow.wag(t);
      // ingredients rain in
      for (const it of items) {
        const d = drop(t, it.at, 8, it.y1, 30, 0.25);
        it.m.visible = t >= it.at;
        it.m.position.y = d.y;
        it.m.rotation.x = d.falling ? (t - it.at) * it.spin : 0;
      }
    },
    overlay(g, t) {
      caption(g, segment.text.ask, 540, 1340, pop(t, B.ask + 0.05, 0.25) * (1 - seg(t, B.think, B.think + 0.1)), { size: 76, fill: P.pink });
      // 40 SECONDS LATER
      if (t > B.later && t < B.rain) {
        g.save();
        g.fillStyle = `rgba(17,17,17,${0.85 * bump(t, B.later, B.rain)})`;
        g.fillRect(0, 0, 1080, 1920);
        g.restore();
        outlined(g, segment.text.later, 540, 900, { size: 96, scale: pop(t, B.later, 0.2), fill: P.yellow, rot: -0.04, lw: 18 });
      }
      flash(g, 0.5 * (1 - seg(t, B.rain, B.rain + 0.2)) * (t >= B.rain ? 1 : 0));
      // the basket lines pop in, app style
      segment.text.items.forEach((name, i) => {
        const k = pop(t, B.rain + 0.15 + i * 0.12, 0.2) * (1 - seg(t, B.bonk - 0.1, B.bonk));
        if (k <= 0) return;
        g.save();
        g.translate(i % 2 ? 760 : 320, 1240 + Math.floor(i / 2) * 76);
        g.scale(k, k);
        chip(g, `${name} ✓`, -170, -28, { fill: i < 3 ? P.lime : "#ffffff", size: 34 });
        g.restore();
      });
      if (t > B.rain + 0.1 && t < B.bonk) {
        g.save();
        g.translate(540, 1170);
        g.scale(pop(t, B.rain + 0.1, 0.2), pop(t, B.rain + 0.1, 0.2));
        chip(g, `🍰 ${segment.text.app}`, -150, -28, { fill: P.yellow, size: 34 });
        g.restore();
      }
      boxCaption(g, segment.text.back, 540, 1380, pop(t, B.bonk + 0.15, 0.25), { size: 54 });
    },
  };
}
