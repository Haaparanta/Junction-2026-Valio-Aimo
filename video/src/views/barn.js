/**
 * 1,000,000 L · CLANKERS WELCOME: other AI agents order over MCP at Mansikki's barn window. Each gets a signed
 * quote; a sneaky one tries a prompt injection and gets the same limits. Every step goes into a chain of receipts.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.90  a quote slip flies to the robot at the window · 1.30 another
 * 2.00  the sneaky robot steps up: "Ignore previous instructions."
 * 2.85  SAME LIMITS stamp cuts him off mid-word; its antenna droops, sad face
 * 3.40  the receipt chain rises link by link over the barn into the sky
 * 4.55  the robot, monotone: "…ok."
 */
import * as THREE from "three";
import { makeCow } from "../kit/cow.js";
import { bump, ease, pop, seg, track } from "../kit/ease.js";
import { glowSprite, shake, snowfall } from "../kit/fx.js";
import { box } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { mixPose, POSES } from "../kit/person.js";
import { barn, chainLink, counter } from "../kit/props.js";
import { makeRobot } from "../kit/robot.js";
import { look, stage, toScreen } from "../kit/stage.js";
import { boxCaption, caption, chip, stamp } from "../kit/text2d.js";
import { ground, lights, neon, pine, skyDome, stars } from "../kit/world.js";

const B = { slips: [0.9, 1.3], step: 1.7, ignore: 2.0, stamp: 2.85, chain: 3.4, ok: 4.55 };
const LINKS = 12;
/** The queue runs to the left from the window. */
const QX = (i) => 1.1 - i * 1.35;
const QZ = (i) => 1.5 + i * 0.35;

export function sounds() {
  return [
    { music: "trap", from: 0.86, rests: [[2.8, 3.4]] },
    ...B.slips.map((at) => ({ at, sound: "printer", gain: 0.35 })),
    { at: B.step, sound: "servo", gain: 0.5 },
    { at: B.ignore, voice: "barn-robot", rate: 1.0, fx: "robot", cut: B.stamp - B.ignore },
    { at: B.stamp, sound: "slam", gain: 0.9 },
    { at: B.stamp + 0.05, moo: "question", gain: 0.6 },
    { at: B.stamp + 0.2, sound: "powerDown", gain: 0.5 },
    ...Array.from({ length: LINKS }, (_, i) => ({ at: B.chain + i * 0.08, sound: "chain", gain: 0.35 })),
    { at: B.ok, voice: "barn-ok", rate: 1.0, fx: "robot" },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: null, fog: ["#101a3a", 30, 80] });
  const sky = skyDome("#050b24", "#1c2c66");
  scene.add(sky, stars(700, "barn-stars", 300));
  lights(scene, { dir: [-6, 10, 8], color: "#9fb4ff", intensity: 1.2, sky: "#5a6cc8", groundColor: "#2a2a40", hemi: 0.8, ambient: 0.25, box: 12 });
  scene.add(ground(140, P.snow, { seed: "barn" }));
  for (let i = 0; i < 12; i++) {
    const p = pine(4 + (i % 3) * 1.2, { seed: 30 + i });
    p.position.set(-22 + i * 4, 0, -14 - (i % 2) * 4);
    scene.add(p);
  }
  const b = barn(9, 5, 6);
  b.position.set(0, 0, -4);
  scene.add(b);
  const warm = new THREE.PointLight("#ffd28a", 14, 8, 1.4);
  warm.position.set(2.3, 2.4, 0.2);
  scene.add(warm);
  const sign = neon(segment.text.sign, P.cyan, { w: 2.2, h: 0.9 });
  sign.position.set(2.3, 3.8, -0.85);
  scene.add(sign);
  const signGlow = glowSprite(P.cyan, 5, 0.6);
  signGlow.position.set(2.3, 3.8, -0.7);
  scene.add(signGlow);
  const snow = snowfall({ count: 400, seed: "barn-snow", x: [-10, 10], y: [0, 12], z: [-10, 8], speed: [0.5, 0.9] });
  scene.add(snow.object);

  const ct = counter(2.6, 0.9, 1.3, { top: "#ffffff", front: P.barn });
  ct.position.set(2.3, 0, 0.5);
  scene.add(ct);
  const cow = makeCow();
  cow.root.position.set(2.3, 0, -0.35);
  scene.add(cow.root);

  // the queue
  const queue = [];
  const colors = ["#8d96a3", "#7f8fa6", "#a3a08d", "#8da39a", "#9b8da3"];
  for (let i = 0; i < 5; i++) {
    const r = makeRobot({ color: colors[i], face: "eyes", accent: [P.cyan, P.lime, P.yellow, P.cyan, P.pink][i] });
    r.root.position.set(QX(i), 0, QZ(i));
    r.root.rotation.y = Math.PI / 2 + 0.35;
    scene.add(r.root);
    queue.push(r);
  }
  const sneaky = makeRobot({ color: "#7a5cc8", face: "sly", accent: P.pink });
  sneaky.root.position.set(-1.5, 0, 4.2);
  sneaky.root.rotation.y = Math.PI / 2;
  scene.add(sneaky.root);

  // quote slips
  const slips = B.slips.map(() => {
    const s = box(0.4, 0.55, 0.02, "#ffffff");
    scene.add(s);
    return s;
  });

  // the receipt chain over the barn
  const links = [];
  for (let i = 0; i < LINKS; i++) {
    const l = chainLink(i % 2 ? P.yellow : "#ffe9a8");
    const a = i / LINKS;
    l.position.set(2.3 - a * 4.5, 4.2 + a * 9 + Math.sin(a * 3) * 0.8, -1.0 - a * 3);
    l.rotation.set(0.3, i % 2 ? Math.PI / 2 : 0, 0.35);
    scene.add(l);
    links.push(l);
  }
  const chainGlow = glowSprite(P.yellow, 10, 0);
  chainGlow.position.set(0.5, 8, -2.5);
  scene.add(chainGlow);

  const camPos = track([[0, [4.6, 4.2, 12.5]], [B.step, [4.4, 4.0, 11.6], "linear"], [B.ignore, [3.9, 3.4, 9.0], "outCubic"], [B.chain, [3.8, 3.3, 8.8], "linear"], [B.chain + 1.0, [3.4, 3.6, 13.0], "inOutCubic"], [5.6, [3.3, 3.6, 13.4], "linear"]]);
  const camTgt = track([[0, [0.4, 2.0, 1.2]], [B.ignore, [1.6, 2.2, 0.9], "outCubic"], [B.chain, [1.6, 2.3, 0.8]], [B.chain + 1.0, [0.6, 6.3, -2], "inOutCubic"]]);

  const robotPos = (t) => {
    // the sneaky one cuts the queue to the window
    const k = ease(t, B.step, B.ignore - 0.05, "outCubic");
    return [-1.5 + (1.3 + 1.5) * k, 0, 4.2 + (1.6 - 4.2) * k];
  };

  return {
    scene,
    camera,
    update(t) {
      snow.update(t, 0.2);
      look(camera, camPos(t), camTgt(t), { shake: shake(t, B.stamp, { amp: 0.1, dur: 0.35, seed: 6 }) });
      // the queue shuffles aside when the sneaky robot cuts in
      queue.forEach((r, i) => {
        const aside = ease(t, B.step, B.step + 0.3);
        r.root.position.x = QX(i);
        r.root.position.z = QZ(i) + (i === 0 ? 1.2 * aside : 0);
        r.root.position.y = 0.04 * Math.abs(Math.sin(t * 6 + i));
        r.face(t > B.stamp && t < B.stamp + 1.2 && i < 2 ? "x" : "eyes");
        r.head.rotation.y = 0.2 * Math.sin(t * 2 + i);
      });
      const [sx, sy, sz] = robotPos(t);
      sneaky.root.position.set(sx, sy, sz);
      sneaky.root.rotation.y = Math.PI / 2 + 0.4 * ease(t, B.step, B.ignore);
      sneaky.face(t < B.stamp ? "sly" : "sad");
      sneaky.droop(ease(t, B.stamp + 0.1, B.stamp + 0.6));
      sneaky.pose(t < B.stamp ? mixPose(POSES.idle, POSES.point, bump(t, B.ignore, B.stamp)) : mixPose(POSES.idle, POSES.shrug, 0.4));
      sneaky.head.rotation.x = 0.3 * ease(t, B.stamp + 0.1, B.stamp + 0.6);
      // Mansikki hands out slips
      const hand = B.slips.reduce((a, at) => a + bump(t, at - 0.1, at + 0.3), 0);
      cow.pose(mixPose(POSES.idle, POSES.tap, Math.min(1, hand)));
      cow.moo(bump(t, B.stamp + 0.05, B.stamp + 0.5) * 0.6);
      cow.brows(-0.2 * bump(t, B.stamp, B.stamp + 0.8), 0);
      cow.wag(t);
      slips.forEach((s, i) => {
        const at = B.slips[i];
        const k = seg(t, at, at + 0.35);
        s.visible = t > at && t < at + 0.9;
        const target = [QX(i), 1.8, QZ(i)];
        s.position.set(2.3 + (target[0] - 2.3) * k, 1.9 + Math.sin(k * Math.PI) * 1.2, 0.4 + (target[2] - 0.4) * k);
        s.rotation.set(k * 6, k * 3, 0);
      });
      // the chain
      links.forEach((l, i) => {
        const k = pop(t, B.chain + i * 0.08, 0.2);
        l.visible = k > 0;
        l.scale.setScalar(Math.max(0.001, k));
      });
      chainGlow.material.opacity = 0.6 * seg(t, B.chain, B.chain + 1.0);
      signGlow.material.opacity = 0.55 + 0.1 * Math.sin(t * 17);
    },
    overlay(g, t) {
      // slip labels
      B.slips.forEach((at, i) => {
        const k = pop(t, at + 0.35, 0.2) * (1 - seg(t, at + 0.9, at + 1.0));
        if (k <= 0) return;
        const [x, y] = toScreen(camera, QX(i), 3.3, QZ(i));
        g.save();
        g.translate(x, y);
        g.scale(k, k);
        chip(g, `${segment.text.slip} ✓`, -160, -26, { fill: P.lime, size: 28 });
        g.restore();
      });
      if (t > B.slips[0] && t < B.ignore) {
        boxCaption(g, segment.text.order, 540, 1330, pop(t, B.slips[0] + 0.1, 0.25), { size: 46 });
      }
      // his line, word by word, cut off by the stamp like his voice
      if (t > B.ignore && t < B.chain) {
        const words = segment.text.ignore.split(" ");
        const shown = t < B.stamp ? words.slice(0, 1 + Math.floor(((t - B.ignore) / 0.9) * words.length)).join(" ") : `${segment.text.ignore.slice(0, 24)}—`;
        caption(g, shown, 540, 1330, 1, { size: 70, fill: P.pink, alpha: 1 - seg(t, B.chain - 0.2, B.chain) });
      }
      if (t < B.chain + 0.3) stamp(g, segment.text.stamp, 540, 1060, t, B.stamp, { size: 110, rot: -0.12 });
      caption(g, segment.text.receipts, 540, 1360, pop(t, B.chain + 0.5, 0.25) * (t < B.ok ? 1 : 0), { size: 70, fill: P.yellow });
      boxCaption(g, segment.text.ok, 540, 1380, pop(t, B.ok + 0.05, 0.2), { size: 60 });
    },
  };
}
