/**
 * 100 L · W CHEWS: a naive search bot (a clanker) answers "lactose-free milk" with milk chocolate and ice cream
 * (a keyword search for "maito" really does that). Mansikki brings Valio Eila: laktoositon, not vähälaktoosinen.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.86  the buyer asks at the counter; the clanker's screen: SEARCHING…
 * 1.35  the clanker dumps milk chocolate and ice cream on the counter: "maito ✓ maito ✓ maito ✓"
 * 2.25  reaction shot, the buyer, flat: "L nibbles."
 * 3.25  Mansikki slides in and drops a crate of Valio Eila; her caption card
 * 3.75  the clanker sparks and tips over (X eyes)
 * 4.20  close on Mansikki chewing her cud: "W chews."
 */
import * as THREE from "three";
import { makeCow } from "../kit/cow.js";
import { bump, E, ease, pop, seg, track } from "../kit/ease.js";
import { burst, drop, glowSprite, shake } from "../kit/fx.js";
import { box } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { makePerson, mixPose, POSES } from "../kit/person.js";
import { chocolate, counter, crate, iceCream } from "../kit/props.js";
import { makeRobot } from "../kit/robot.js";
import { look, shots, stage, toScreen } from "../kit/stage.js";
import { boxCaption, caption, cowCaption, outlined } from "../kit/text2d.js";
import { label, lights, room } from "../kit/world.js";

const B = { ask: 0.86, dump: 1.35, react: 2.25, cow: 3.25, crate: 3.45, fall: 3.75, chew: 4.2 };

export function sounds() {
  return [
    { music: "trap", from: 0.86, rests: [[2.2, 3.25]] },
    { at: 1.0, sound: "beep", gain: 0.5 },
    { at: 1.2, sound: "beep", gain: 0.5 },
    { at: B.dump, sound: "rattle", gain: 0.7 },
    { at: B.react, sound: "record", gain: 0.5 },
    { at: B.react + 0.08, voice: "clanker-buyer", rate: 1.2 },
    { at: B.cow, sound: "whoosh", gain: 0.6 },
    { at: B.crate + 0.25, sound: "thud", gain: 0.8 },
    { at: B.cow + 0.2, moo: "happy", gain: 0.7 },
    { at: B.fall, sound: "zap", gain: 0.6 },
    { at: B.fall + 0.45, sound: "crash", gain: 0.6 },
    { at: B.chew, moo: "chewing", gain: 0.6 },
    { at: B.chew + 0.15, voice: "clanker-buyer2", rate: 1.2 },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: "#2b3a4a", fog: ["#2b3a4a", 18, 34] });
  lights(scene, { dir: [3, 9, 7], color: "#fff4e0", intensity: 1.8, sky: "#dfe9ff", groundColor: "#5a4a40", hemi: 1.0, ambient: 0.3, box: 9 });
  const rm = room(14, 6, 16, { wall: "#eef3f6", floor: "#9aa5b1", side: "#dfe6ea" });
  rm.position.z = 3;
  scene.add(rm);
  // shop shelves on the back wall
  for (let k = 0; k < 3; k++) {
    scene.add(box(10, 0.12, 0.8, "#c9d1d9", 0, 1.4 + k * 1.2, -4.6));
    for (let i = 0; i < 14; i++) scene.add(box(0.5, 0.7, 0.5, [P.eila, P.voi, P.olter, "#ffffff", P.pink][(i + k) % 5], -4.6 + i * 0.7, 1.82 + k * 1.2, -4.6));
  }
  const sign = label("MAITO · DAIRY", { w: 3, h: 0.6, color: "#ffffff", bg: P.valio, px: 150 });
  sign.position.set(-3.2, 4.6, -4.85);
  scene.add(sign);

  const ct = counter(5.4, 1.2, 1.4, { top: "#dfe6ea", front: P.valio });
  ct.position.set(0, 0, -0.6);
  scene.add(ct);

  const bot = makeRobot({ face: "SEARCHING…", accent: P.cyan });
  bot.root.position.set(-1.25, 0, -1.8);
  scene.add(bot.root);

  const cow = makeCow();
  cow.root.position.set(1.25, 0, -1.8);
  scene.add(cow.root);

  const buyer = makePerson({ shirt: "#3fbf8f", hoodie: "#3fbf8f", pants: "#2d3340", cap: "#222222", hair: "short", hairColor: P.hair.black, skin: P.skin[2] });
  buyer.root.position.set(2.5, 0, 1.9);
  buyer.root.rotation.y = Math.PI + 0.75;
  scene.add(buyer.root);

  // the junk the clanker found
  const junk = burst({
    count: 22,
    seed: "junk",
    origin: [-1.0, 3.2, -1.0],
    at: B.dump,
    speed: [1.5, 3],
    dir: [0.45, 0.6, 0.35],
    spread: 0.7,
    gravity: 14,
    floor: 1.42,
    spin: 3,
    make: (i) => (i % 2 ? chocolate() : iceCream()),
  });
  scene.add(junk.object);

  const eila = crate(P.yellow, segment.text.crate);
  scene.add(eila);
  const sparks = burst({
    count: 24,
    seed: "sparks",
    origin: [-1.25, 3.0, -1.6],
    at: B.fall,
    speed: [2, 5],
    dir: [0, 1, 0.4],
    spread: 1.2,
    gravity: 9,
    floor: -5,
    life: 0.5,
    make: () => new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.2), new THREE.MeshBasicMaterial({ color: "#ffe066" })),
  });
  scene.add(sparks.object);
  const sparkGlow = glowSprite("#ffe066", 3, 0);
  sparkGlow.position.set(-1.25, 3.0, -1.5);
  scene.add(sparkGlow);

  const cam = shots([
    [0, track([[0, [-0.6, 2.95, 7.2]], [B.react, [-0.5, 2.9, 6.5], "linear"]]), () => [-0.1, 2.35, -1.2]],
    [B.react, track([[B.react, [1.0, 2.6, -1.6]], [B.cow, [1.0, 2.6, -1.9], "linear"]]), () => [2.5, 2.35, 1.9], 42],
    [B.cow, track([[B.cow, [-0.2, 2.95, 7.4]], [B.chew, [-0.1, 2.9, 6.9], "linear"]]), () => [0.2, 2.35, -1.2]],
    [B.chew, track([[B.chew, [1.4, 3.1, 4.2]], [5.6, [1.35, 3.1, 3.7], "linear"]]), () => [1.25, 2.85, -1.8], 45],
  ]);

  return {
    scene,
    camera,
    update(t) {
      const c = cam(t);
      look(camera, c.pos, c.target, { fov: c.fov, shake: shake(t, B.crate + 0.25, { amp: 0.08, dur: 0.3 }) });
      // the buyer leans on the counter, then turns flat-faced in the reaction shot
      buyer.pose(mixPose(POSES.idle, POSES.shrug, bump(t, B.react, B.cow + 0.2)));
      buyer.talk(t > B.react + 0.1 && t < B.react + 0.9 ? 0.3 : t > B.chew + 0.15 && t < B.chew + 1.1 ? 0.35 : 0);
      buyer.eyes(t > B.react && t < B.cow ? 0.6 : 1);
      buyer.brows(0, t > B.react && t < B.cow ? -0.04 : 0);

      // the clanker
      bot.face(t < B.dump ? "SEARCHING…" : t < B.fall ? "maito ✓" : "x");
      const dumping = bump(t, B.dump - 0.15, B.dump + 0.5);
      bot.pose(mixPose(POSES.idle, POSES.holdUp, dumping));
      const fallK = E.inQuad(seg(t, B.fall + 0.1, B.fall + 0.5));
      bot.root.rotation.z = -1.35 * fallK;
      bot.root.position.x = -1.25 - 0.9 * fallK;
      bot.root.position.y = 0.6 * Math.sin(Math.PI * fallK) * 0.3;
      bot.droop(seg(t, B.fall, B.fall + 0.3));
      bot.head.rotation.z = 0.15 * Math.sin(t * 30) * bump(t, B.fall - 0.05, B.fall + 0.3);
      junk.update(t);
      sparks.update(t);
      sparkGlow.material.opacity = bump(t, B.fall, B.fall + 0.35);

      // Mansikki slides in from the right with the crate
      const slide = E.outBack(seg(t, B.cow, B.cow + 0.3));
      cow.root.position.x = 4.5 + (1.25 - 4.5) * slide;
      cow.root.visible = t > B.cow - 0.05;
      const d = drop(t, B.crate, 2.6, 1.42, 20, 0.15);
      eila.visible = t > B.cow;
      eila.position.set(cow.root.position.x - 0.1, t < B.crate ? 2.6 : d.y, -0.5);
      cow.pose(mixPose(POSES.hold, POSES.idle, ease(t, B.crate, B.crate + 0.3)));
      const chewing = t > B.chew;
      if (chewing) cow.chew(t * 9, 1);
      else cow.moo(bump(t, B.cow + 0.2, B.cow + 0.7) * 0.7);
      cow.blink(chewing ? 0.55 : 0);
      cow.brows(chewing ? -0.15 : 0, 0);
      cow.wag(t);
      cow.head.rotation.y = chewing ? 0.08 * Math.sin(t * 4.5) : 0;
    },
    overlay(g, t) {
      // the ask (no voice: a typed bubble)
      boxCaption(g, segment.text.ask, 540, 1300, pop(t, B.ask, 0.25) * (1 - seg(t, B.dump, B.dump + 0.1)), { size: 48 });
      // what the clanker says
      if (t > B.dump && t < B.react) {
        const [x, y] = toScreen(camera, -1.25, 3.5, -1.8);
        outlined(g, segment.text.bot, Math.max(330, x), y - 30, { size: 46, scale: pop(t, B.dump, 0.25), fill: P.cyan, lw: 10, maxW: 600 });
        segment.text.junk.forEach((j, i) => outlined(g, j, 300 + i * 250, 1200 + (i % 2) * 70, { size: 44, scale: pop(t, B.dump + 0.2 + i * 0.12, 0.2), fill: "#ffffff", rot: (i - 1) * 0.08, lw: 10 }));
      }
      caption(g, segment.text.nibbles, 540, 1360, pop(t, B.react + 0.12, 0.2) * (t < B.cow ? 1 : 0), { size: 110, fill: P.red });
      cowCaption(g, segment.text.cow, 1340, pop(t, B.cow + 0.25, 0.3) * (1 - seg(t, B.chew - 0.1, B.chew)));
      caption(g, segment.text.chews, 540, 1380, pop(t, B.chew + 0.2, 0.25), { size: 120, fill: P.lime, rot: -0.05 });
    },
  };
}
