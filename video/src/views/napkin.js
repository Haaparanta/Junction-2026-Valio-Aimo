/**
 * 67 L · SHE CAN READ??: a sitsit (Finnish student dinner party) whose shopping list is a napkin.
 * Photo to basket: the photo becomes basket lines; what is not in the catalogue stays NOT FOUND.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.86  the organiser holds the napkin up to the camera (2D close-up)
 * 1.90  phone flash
 * 2.05  the app: lines land in the basket one by one (2.30, 2.50, 2.70)
 * 2.95  "kebab??" NOT FOUND · 3.15 "sleep" NOT FOUND (the phone shakes)
 * 3.65  she does the 6-7 hands; a 6 and a 7 pop at her hands: "SIX SEVEN!"; the table cheers
 */
import * as THREE from "three";
import { bump, E, ease, pop, seg, track } from "../kit/ease.js";
import { burst, flash, glowSprite, shake } from "../kit/fx.js";
import { box, glow } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { makePerson, makePhone, mixPose, POSES, sixSevenPose } from "../kit/person.js";
import { candle, table } from "../kit/props.js";
import { noise1 } from "../kit/rand.js";
import { look, stage, toScreen } from "../kit/stage.js";
import { basketLine, caption, chip, outlined, phone, timerBadge } from "../kit/text2d.js";
import { lights, room } from "../kit/world.js";

const B = { napkin: 0.86, flash: 1.9, phone: 2.05, lines: [2.3, 2.5, 2.7, 2.95, 3.15], shake: 3.15, out: 3.55, six: 3.65 };

export function sounds() {
  return [
    { music: "trap", from: 0.86, rests: [[1.85, 2.05], [3.45, 3.65]] },
    { at: 1.1, sound: "paper", gain: 0.5 },
    { at: B.flash, sound: "shutter", gain: 0.8 },
    ...B.lines.slice(0, 3).map((at) => ({ at, sound: "pop", gain: 0.6 })),
    { at: B.lines[3], sound: "error", gain: 0.55 },
    { at: B.lines[4], sound: "error", gain: 0.65 },
    { at: B.shake + 0.05, sound: "sadTrombone", gain: 0.5 },
    { at: B.six - 0.05, sound: "boom", gain: 0.7 },
    { at: B.six, voice: "napkin-organiser", rate: 1.0 },
    { at: B.six + 0.1, sound: "cheer", gain: 0.45 },
  ];
}

const HAND = "'Bradley Hand', 'Marker Felt', 'Chalkboard SE', cursive";

export function build(segment) {
  const { scene, camera } = stage({ background: "#2a1a14", fog: ["#2a1a14", 16, 34] });
  lights(scene, { dir: [4, 8, 6], color: "#ffd9a8", intensity: 1.3, sky: "#ffcf9e", groundColor: "#4a2a1a", hemi: 0.9, ambient: 0.25, box: 10 });
  const rm = room(16, 6, 18, { wall: "#7a3b2e", floor: "#5a3a26", side: "#6a3226" });
  rm.position.z = 5;
  scene.add(rm);
  // bunting across the back wall
  const colors = [P.yellow, P.pink, P.cyan, P.lime, P.orange];
  for (let i = 0; i < 22; i++) {
    const tri = new THREE.Mesh(new THREE.ConeGeometry(0.22, 0.45, 3), glow(colors[i % colors.length]));
    tri.rotation.z = Math.PI;
    tri.position.set(-7 + i * 0.66, 4.3 - Math.sin((i / 21) * Math.PI) * 0.6, -3.85);
    scene.add(tri);
  }
  // the long table with white paper, candles, songbooks
  const tb = table(12, 1.8, 1.15, { cloth: "#ffffff", legs: "#3a2618" });
  tb.position.set(0, 0, -1.6);
  scene.add(tb);
  const flames = [];
  for (let i = 0; i < 6; i++) {
    const c = candle();
    c.position.set(-5 + i * 2, 1.21, -1.6);
    scene.add(c);
    const fl = glowSprite("#ffb347", 0.9, 0.8);
    fl.position.set(-5 + i * 2, 1.72, -1.6);
    scene.add(fl);
    flames.push(fl);
  }
  for (let i = 0; i < 8; i++) scene.add(box(0.32, 0.06, 0.44, colors[(i * 3) % colors.length], -5.5 + i * 1.5, 1.24, -1.1));
  const candleLight = new THREE.PointLight("#ffb347", 10, 9, 1.4);
  candleLight.position.set(0, 2.2, -1.2);
  scene.add(candleLight);

  // students at the table, in overalls
  const sitters = [];
  const overalls = [P.blue, P.lime, P.yellow, "#8a5cf6", P.orange];
  for (let i = 0; i < 5; i++) {
    const s = makePerson({ shirt: "#ffffff", overalls: overalls[i], patches: true, hair: i % 2 ? "long" : "short", hairColor: Object.values(P.hair)[i % 4], skin: P.skin[i % 5] });
    s.root.position.set(-4 + i * 2, 0.35, -2.75);
    s.pose(POSES.sit);
    scene.add(s.root);
    sitters.push(s);
  }

  // the organiser in pink overalls
  const org = makePerson({ shirt: "#ffffff", overalls: P.pink, patches: true, hair: "ponytail", hairColor: P.hair.ginger, skin: P.skin[4] });
  org.root.position.set(0, 0, 1.2);
  scene.add(org.root);
  const ph = makePhone();
  org.hold(ph, "R", 0, -0.62, 0.12);
  ph.rotation.x = -1.4;
  const nap = box(0.6, 0.6, 0.02, "#fffdf6", 0, -0.7, 0.2);
  org.hold(nap, "L", 0, -0.75, 0.22);

  const confetti = burst({
    count: 50,
    seed: "napkin-confetti",
    origin: [0, 2.6, -1.4],
    at: B.six + 0.05,
    speed: [5, 8],
    dir: [0, 1, -0.3],
    spread: 0.8,
    gravity: 6,
    floor: 1.22,
    spin: 8,
    make: (i, r) => new THREE.Mesh(new THREE.PlaneGeometry(0.14, 0.2), glow(r.pick(colors), { side: THREE.DoubleSide, fog: true })),
  });
  scene.add(confetti.object);

  const cam = track([[0, [0, 2.7, 9.0]], [B.six, [0, 2.6, 8.4], "linear"], [B.six + 0.2, [0, 2.5, 7.9], "outQuart"], [5.6, [0, 2.5, 7.6], "linear"]]);

  const handL = new THREE.Vector3();
  const handR = new THREE.Vector3();

  return {
    scene,
    camera,
    update(t) {
      look(camera, cam(t), [0, 1.85, 0], { shake: shake(t, B.six, { amp: 0.08, dur: 0.3, seed: 3 }) });
      for (const [i, f] of flames.entries()) f.scale.setScalar(0.8 + 0.15 * noise1(t * 6, i));
      // organiser: napkin up, then phone, then 6-7
      const up = ease(t, 0.6, 0.9);
      const six = ease(t, B.six - 0.1, B.six + 0.05);
      let pose = mixPose(POSES.idle, { ...POSES.phone, shL: [-1.7, 0, -0.1], elL: [-0.6, 0, 0] }, up);
      pose = mixPose(pose, sixSevenPose(t, 9), six);
      org.pose(pose);
      nap.visible = t < B.phone;
      ph.visible = t >= B.flash - 0.3;
      org.talk(t > B.six && t < B.six + 0.9 ? Math.max(0, noise1(t * 12, 2) * 0.5 + 0.5) : 0);
      org.eyes(1 + 0.3 * six);
      org.brows(-0.2 * six, 0.05 * six);
      org.root.position.y = 0.08 * Math.abs(Math.sin(t * 9)) * six;
      // the table cheers on the 6-7
      sitters.forEach((s, i) => {
        const c = ease(t, B.six + i * 0.04, B.six + 0.2 + i * 0.04);
        s.pose(mixPose(POSES.sit, { ...POSES.sit, shL: [0, 0, 2.6], shR: [0, 0, -2.6], elL: [0, 0, 0.3], elR: [0, 0, -0.3] }, c * (0.7 + 0.3 * Math.sin(t * 10 + i))));
        s.talk(c * (0.5 + 0.5 * Math.sin(t * 13 + i)));
        s.root.position.y = 0.35 + 0.06 * c * Math.abs(Math.sin(t * 8 + i));
      });
      confetti.update(t);
      org.handR.getWorldPosition(handR);
      org.handL.getWorldPosition(handL);
    },
    overlay(g, t) {
      flash(g, 0.9 * (1 - seg(t, B.flash, B.flash + 0.25)) * (t >= B.flash ? 1 : 0));
      // napkin close-up
      const nk = t < B.flash ? pop(t, B.napkin, 0.3) : 1 - E.inCubic(seg(t, B.flash, B.phone + 0.1));
      if (nk > 0) drawNapkin(g, segment.text.napkin, 540, 830 - (t > B.flash ? 120 * seg(t, B.flash, B.phone) : 0), nk);
      // the app on the phone
      const pk = t < B.out ? pop(t, B.phone, 0.3) : 1 - E.inCubic(seg(t, B.out, B.six));
      const shk = t > B.shake && t < B.shake + 0.35 ? Math.sin(t * 80) * 10 * (1 - seg(t, B.shake, B.shake + 0.35)) : 0;
      phone(g, 540 + shk, 880, pk, (sg, w) => {
        chip(sg, "📷 Photo to basket", 24, 150, { fill: P.yellow, size: 28 });
        sg.fillStyle = P.ink;
        sg.font = `40px 'Archivo Black'`;
        sg.textAlign = "left";
        sg.fillText("Basket", 26, 268);
        timerBadge(sg, "read in 5 s", w - 140, 250, pop(t, B.lines[0], 0.3), P.lime);
        const rows = [...segment.text.found.map((n) => [n, "✓", "ok"]), ...segment.text.missing.map((n) => [n, "", "missing"])];
        const qty = segment.text.qty;
        rows.forEach(([name, , status], i) => basketLine(sg, 24, 310 + i * 96, w - 54, name, qty[i] ?? "", status, pop(t, B.lines[i], 0.25)));
        if (t > B.lines[4]) {
          sg.save();
          sg.globalAlpha = 0.25 * bump(t, B.lines[4], B.lines[4] + 0.5);
          sg.fillStyle = P.red;
          sg.fillRect(0, 0, w, 2000);
          sg.restore();
        }
      }, { w: 560, h: 980 });
      caption(g, "sleep: NOT FOUND 💀", 540, 1440, pop(t, B.lines[4] + 0.1, 0.25) * (1 - seg(t, B.out, B.six)), { size: 64, fill: P.red });
      // 6 and 7 at her hands
      if (t > B.six) {
        const [lx, ly] = toScreen(camera, handR.x, handR.y, handR.z);
        const [rx, ry] = toScreen(camera, handL.x, handL.y, handL.z);
        const s = Math.sin(t * 9);
        outlined(g, "6", lx - 40, ly - 90 + s * 20, { size: 150, scale: pop(t, B.six, 0.2), fill: P.yellow, lw: 22 });
        outlined(g, "7", rx + 40, ry - 90 - s * 20, { size: 150, scale: pop(t, B.six + 0.12, 0.2), fill: P.cyan, lw: 22 });
        caption(g, segment.text.shout, 540, 1400, pop(t, B.six + 0.05, 0.25), { size: 110, fill: P.pink, rot: -0.04 });
      }
    },
  };
}

function drawNapkin(g, lines, x, y, k) {
  g.save();
  g.translate(x, y);
  g.rotate(-0.07);
  g.scale(k, k);
  g.fillStyle = "rgba(0,0,0,0.35)";
  g.fillRect(-300 + 16, -330 + 22, 600, 660);
  g.fillStyle = "#fffdf6";
  g.beginPath();
  g.moveTo(-300, -330);
  g.lineTo(290, -320);
  g.lineTo(305, 320);
  g.lineTo(-295, 335);
  g.closePath();
  g.fill();
  g.strokeStyle = "rgba(0,0,0,0.08)";
  g.lineWidth = 3;
  g.beginPath();
  g.moveTo(0, -325);
  g.lineTo(5, 330);
  g.moveTo(-300, 0);
  g.lineTo(305, 5);
  g.stroke();
  // a coffee ring
  g.strokeStyle = "rgba(140,90,40,0.25)";
  g.lineWidth = 10;
  g.beginPath();
  g.arc(170, 200, 70, 0.3, 5.6);
  g.stroke();
  g.fillStyle = "#1f3a8a";
  g.textAlign = "left";
  g.textBaseline = "middle";
  lines.forEach((l, i) => {
    g.font = `${i === 4 ? 72 : 64}px ${HAND}`;
    g.save();
    g.translate(-240, -230 + i * 112);
    g.rotate((i % 2 ? 1 : -1) * 0.03);
    g.fillText(l, 0, 0);
    g.restore();
  });
  // "sleep" gets a doodle underline
  g.strokeStyle = "#c41e3a";
  g.lineWidth = 6;
  g.beginPath();
  g.moveTo(-240, 250);
  for (let i = 0; i < 6; i++) g.lineTo(-240 + i * 40, 250 + (i % 2 ? 12 : -4));
  g.stroke();
  g.restore();
}

