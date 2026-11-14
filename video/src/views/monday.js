/**
 * 1,000 L · GRR MONDAYS: Chef Aada needs 1,000 litres by Monday. A fixed, signed quote lands at once: 1,010.00 €,
 * order by Sun 17:00. It is over her 500 € cap, so it goes to the manager, head chef Mikko, who is in the sauna
 * (the Embassy of Finland closed for its pre-Christmas sauna, Nov 2026). He approves. "Hyvä."
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.86  Aada with her phone: "A thousand litres by Monday."
 * 1.55  the quote on her phone; 1.75 the total slams in; SIGNED
 * 2.25  red banner: OVER YOUR 500 € LIMIT → sent to your manager; 2.55 the card whooshes away
 * 2.70  cut to the sauna: steam, "CLOSED FOR SAUNA"
 * 2.95  the approval card on Mikko's phone
 * 3.55  he presses APPROVE; 3.65 APPROVED stamp; water on the stones, a burst of steam
 * 4.35  Mikko, deadpan: "Hyvä."
 */
import * as THREE from "three";
import { bump, E, ease, pop, seg, track } from "../kit/ease.js";
import { glowSprite, shake, steam } from "../kit/fx.js";
import { box } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { makePerson, makePhone, mixPose, POSES } from "../kit/person.js";
import { counter, sauna } from "../kit/props.js";
import { noise1 } from "../kit/rand.js";
import { look, shots, stage } from "../kit/stage.js";
import { boxCaption, brutal, button, caption, chip, DISPLAY, phone, stamp, UI } from "../kit/text2d.js";
import { label, lights, room } from "../kit/world.js";

const B = { ask: 0.86, quote: 1.55, total: 1.75, over: 2.25, away: 2.55, sauna: 2.7, approval: 2.95, press: 3.55, approved: 3.65, hyva: 4.35 };
const SX = 60; // the sauna is built 60 units away and the camera cuts to it

export function sounds() {
  return [
    { music: "trap", from: 0.86, rests: [[2.6, 3.0], [4.3, 5.6]] },
    { at: B.ask + 0.04, voice: "monday-aada", rate: 1.25 },
    { at: B.quote, sound: "whoosh", gain: 0.5 },
    { at: B.total, sound: "kaching", gain: 0.8 },
    { at: B.over, sound: "error", gain: 0.6 },
    { at: B.away, sound: "whoosh", gain: 0.7 },
    { at: B.sauna, sound: "steam", gain: 0.35, dur: 2.9 },
    { at: B.approval, sound: "notify", gain: 0.6 },
    { at: B.press, sound: "click", gain: 0.7 },
    { at: B.approved, sound: "stampLime", gain: 0.7 },
    { at: B.approved + 0.05, sound: "loyly", gain: 0.8 },
    { at: B.hyva, voice: "monday-mikko", rate: 1.0 },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: "#3a2a22" });
  lights(scene, { dir: [4, 9, 7], color: "#fff1dd", intensity: 1.7, sky: "#fff0dc", groundColor: "#6a5040", hemi: 1.0, ambient: 0.3, box: 8 });

  // --- the restaurant kitchen ---
  const rm = room(12, 6, 14, { wall: "#f3e9d8", floor: "#7b5a3c", side: "#e9dcc6" });
  rm.position.z = 3;
  scene.add(rm);
  for (let i = 0; i < 18; i++) scene.add(box(0.6, 0.6, 0.02, i % 2 ? P.tile : "#d9e2ea", -5.1 + i * 0.6, 2.2, -3.88));
  const ct = counter(9, 1.2, 1.4);
  ct.position.set(0, 0, -3.1);
  scene.add(ct);
  const cal = label("MA\n16.11", { w: 1.1, h: 1.2, color: P.red, bg: "#ffffff", px: 200, lit: true });
  cal.position.set(-2.4, 3.6, -3.85);
  scene.add(cal);
  const aada = makePerson({ shirt: "#ffffff", pants: "#2b2b2b", hair: "bun", hairColor: P.hair.brown, skin: P.skin[0] });
  aada.root.position.set(0, 0, 0.4);
  scene.add(aada.root);
  for (let i = 0; i < 3; i++) aada.j.spine.add(box(0.07, 0.07, 0.03, P.ink, -0.15, 0.3 + i * 0.22, 0.27));
  const ph = makePhone();
  aada.hold(ph, "R", 0, -0.62, 0.12);
  ph.rotation.x = -1.4;

  // --- the sauna ---
  const sa = sauna(7, 5, 5);
  sa.position.set(SX, 0, 0);
  scene.add(sa);
  const sign = label("CLOSED\nFOR SAUNA", { w: 1.7, h: 0.9, color: "#3a2010", bg: "#e9c48f", px: 170, lit: true });
  sign.position.set(SX + 1.0, 3.9, -2.38);
  scene.add(sign);
  sa.userData.stove.position.x = 1.5;
  const stoveLight = new THREE.PointLight("#ff9a4a", 22, 9, 1.5);
  stoveLight.position.set(SX + 1.5, 1.8, -1.0);
  scene.add(stoveLight);
  const mikko = makePerson({ towel: true, hair: "short", hairColor: P.hair.grey, beard: true, skin: "#f0b8a0" });
  mikko.root.position.set(SX - 0.7, 0.5, -1.55);
  mikko.pose(POSES.sit);
  scene.add(mikko.root);
  const ph2 = makePhone();
  mikko.hold(ph2, "R", 0, -0.62, 0.12);
  ph2.rotation.x = -1.4;
  const ph2Glow = glowSprite("#bfe3ff", 1.2, 0.6);
  scene.add(ph2Glow);
  const steamA = steam({ count: 30, seed: "sauna", origin: [SX + 1.5, 1.6, -1.6], height: 3.5, period: 2.2, spread: 1.6, size: 1.8, opacity: 0.25 });
  scene.add(steamA.object);
  const steamB = steam({ count: 40, seed: "loyly", origin: [SX + 1.5, 1.6, -1.4], height: 3.0, period: 1.0, spread: 2.5, size: 2.4, opacity: 0.5 });
  scene.add(steamB.object);

  const cam = shots([
    [0, track([[0, [0.5, 2.7, 6.8]], [B.sauna, [0.4, 2.65, 5.8], "linear"]]), () => [0, 2.0, 0.4]],
    [B.sauna, track([[B.sauna, [SX + 0.3, 2.7, 6.2]], [B.hyva, [SX + 0.1, 2.6, 5.2], "linear"], [B.hyva + 0.15, [SX - 0.3, 2.55, 3.6], "outQuart"], [5.6, [SX - 0.3, 2.55, 3.4], "linear"]]), track([[B.sauna, [SX + 0.2, 2.0, -1.2]], [B.hyva, [SX - 0.1, 2.1, -1.3]], [B.hyva + 0.15, [SX - 0.6, 2.45, -1.5], "outQuart"]])],
  ]);

  const phonePos = new THREE.Vector3();

  return {
    scene,
    camera,
    update(t) {
      const c = cam(t);
      look(camera, c.pos, c.target, { fov: c.fov, shake: shake(t, B.total, { amp: 0.05, dur: 0.25 }) });
      aada.pose(mixPose(POSES.phone, POSES.phoneLow, ease(t, B.quote - 0.2, B.quote)));
      aada.talk(t > B.ask && t < B.ask + 1.2 ? Math.max(0, noise1(t * 12, 7) * 0.5 + 0.4) : 0);
      aada.eyes(1 + 0.4 * ease(t, B.over, B.over + 0.1));
      aada.brows(-0.2 * ease(t, B.over, B.over + 0.1), 0.05 * ease(t, B.over, B.over + 0.1));
      // Mikko: phone up, presses approve, ladles water
      const ladle = bump(t, B.approved, B.approved + 0.6);
      mikko.pose(mixPose(mixPose(POSES.sit, { ...POSES.sit, shR: [-0.6, 0, 0.25], elR: [-1.8, 0, 0], shL: [-0.9, 0, -0.3], elL: [-1.2, 0, 0] }, ease(t, B.sauna, B.approval)), { ...POSES.sit, shL: [-1.2, 0, 0.9], elL: [-0.3, 0, 0] }, ladle));
      mikko.talk(t > B.hyva && t < B.hyva + 0.4 ? 0.5 : 0);
      mikko.blink(t > B.hyva - 0.3 ? 0.45 : 0);
      ph2.getWorldPosition(phonePos);
      ph2Glow.position.copy(phonePos);
      steamA.update(t);
      steamB.object.visible = t > B.approved;
      steamB.update(t - B.approved, 1 + 1.5 * bump(t, B.approved, B.approved + 1.2));
      stoveLight.intensity = 22 + 20 * bump(t, B.approved, B.approved + 0.8);
    },
    overlay(g, t) {
      caption(g, segment.text.ask, 540, 1360, pop(t, B.ask + 0.05, 0.25) * (1 - seg(t, B.quote - 0.05, B.quote)), { size: 70 });
      // the quote on Aada's phone
      const away = E.inBack(seg(t, B.away, B.sauna));
      const qk = pop(t, B.quote, 0.3);
      if (t < B.sauna) {
        g.save();
        g.translate(away * 300, -away * 1400);
        g.rotate(away * 0.3);
        phone(g, 540, 900, qk, (sg, w) => quoteScreen(sg, w, t, segment.text), { w: 580, h: 1000 });
        g.restore();
      }
      // the approval in the sauna
      phone(g, 540, 880, pop(t, B.approval, 0.3) * (1 - seg(t, B.hyva - 0.15, B.hyva)), (sg, w) => approvalScreen(sg, w, t, segment.text), { w: 560, h: 940 });
      if (t > B.approved && t < B.hyva) stamp(g, segment.text.approved, 540, 1180, t, B.approved, { color: "#1f7a1f", fill: P.lime, size: 90, rot: -0.1 });
      boxCaption(g, segment.text.hyva, 540, 1380, pop(t, B.hyva + 0.05, 0.25), { size: 64 });
    },
  };
}

function quoteScreen(g, w, t, text) {
  chip(g, "QUOTE", 24, 150, { fill: P.yellow, size: 28 });
  chip(g, text.signed, w - 190, 150, { fill: P.lime, size: 28 });
  brutal(g, 24, 230, w - 58, 420, { fill: "#ffffff", r: 16, bw: 5, shadow: 8 });
  g.fillStyle = P.ink;
  g.textAlign = "left";
  g.font = `700 30px ${UI}`;
  g.fillText(text.product, 48, 290);
  g.font = `700 24px ${UI}`;
  g.fillStyle = "#4a4a4a";
  g.fillText("from stock · excl. VAT · fixed price", 48, 330);
  const k = pop(t, B.total, 0.2);
  g.save();
  g.translate(w / 2, 450);
  g.scale(k * (1 + 0.2 * bump(t, B.total, B.total + 0.2)), k * (1 + 0.2 * bump(t, B.total, B.total + 0.2)));
  g.fillStyle = P.ink;
  g.font = `92px ${DISPLAY}`;
  const fit = Math.min(1, (w - 120) / g.measureText(text.total).width);
  g.font = `${Math.floor(92 * fit)}px ${DISPLAY}`;
  g.textAlign = "center";
  g.fillText(text.total, 0, 30);
  g.restore();
  chip(g, `⏰ ${text.cutoff}`, 48, 560, { fill: P.cyan, size: 28 });
  // the red banner
  const bk = pop(t, B.over, 0.25);
  if (bk > 0) {
    g.save();
    g.translate(w / 2, 760);
    g.scale(bk, bk);
    brutal(g, -(w - 58) / 2, -80, w - 58, 160, { fill: P.red, r: 16, bw: 5, shadow: 8 });
    g.fillStyle = "#ffffff";
    g.textAlign = "center";
    g.font = `30px ${DISPLAY}`;
    g.fillText(text.over, 0, -14);
    g.font = `700 28px ${UI}`;
    g.fillText(text.toManager, 0, 36);
    g.restore();
  }
}

function approvalScreen(g, w, t, text) {
  chip(g, "APPROVAL · head chef Mikko", 24, 150, { fill: P.pink, size: 26 });
  brutal(g, 24, 230, w - 58, 470, { fill: "#ffffff", r: 16, bw: 5, shadow: 8 });
  g.fillStyle = P.ink;
  g.textAlign = "left";
  g.font = `700 28px ${UI}`;
  g.fillText("Chef Aada asks:", 48, 285);
  g.font = `66px ${DISPLAY}`;
  g.fillText(text.total, 48, 370);
  g.font = `700 26px ${UI}`;
  g.fillText(text.product, 48, 420);
  g.fillStyle = "#b00020";
  g.fillText("over her 500 € cap", 48, 460);
  g.fillStyle = P.ink;
  g.fillText("decide before Sun 17:00", 48, 500);
  const pressed = bump(t, B.press, B.press + 0.25);
  button(g, text.approve, 48, 560, w - 106, 96, { fill: P.lime, pressed, size: 40 });
  button(g, "Reject", 48, 720, w - 106, 80, { fill: "#ffffff", size: 30 });
}
