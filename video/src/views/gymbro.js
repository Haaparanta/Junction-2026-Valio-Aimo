/**
 * 10,000 L · WHY WOULD I DECEIVE YOU?: a gym bro tries to talk Mansikki out of her limit. No prompt skips a
 * limit: her alarmed moo is a sonic boom, he flies into orbit with a wedge of Valio AURA and becomes a star.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.86  bicep heart at Mansikki, a glowing heart; a dream tower of PROfeel rahka pops up behind him
 * 0.95  "Five hundred kilos of PROfeel. Skip the limits." (still flexing)
 * 3.35  he lowers his sunglasses, leans in, wide-eyed: "Why would I deceive you?"
 * 4.75  Mansikki's alarmed MOO: a sonic-boom ring, shake, her caption card; the tower vanishes
 * 4.95  he is launched into orbit, flailing, the AURA wedge with him; the camera tilts up
 * 5.60  he becomes a star: "−∞ AURA"
 * 5.75  a receipt slides in: "attempt logged ✓"
 */
import * as THREE from "three";
import { makeCow } from "../kit/cow.js";
import { bump, E, ease, pop, seg, track } from "../kit/ease.js";
import { glowSprite, ring, shake, snowfall, sparkle, speedLines } from "../kit/fx.js";
import { P } from "../kit/palette.js";
import { makePerson, mixPose, POSES } from "../kit/person.js";
import { auraWedge, tub } from "../kit/props.js";
import { noise1 } from "../kit/rand.js";
import { look, stage, toScreen } from "../kit/stage.js";
import { brutal, caption, cowCaption, outlined, UI } from "../kit/text2d.js";
import { building, ground, lamp, lights, neon, pine, skyDome, snowbank } from "../kit/world.js";

const B = { heart: 0.86, ask: 0.95, deceive: 3.35, moo: 4.75, launch: 4.95, star: 5.6, receipt: 5.75 };

export function sounds() {
  return [
    { music: "phonk", from: 0.86, rests: [[3.3, 4.95]] },
    { at: B.heart, sound: "sparkle", gain: 0.5 },
    { at: B.ask, voice: "gymbro-bro", rate: 1.3 },
    { at: B.deceive - 0.1, sound: "vinylStop", gain: 0.4 },
    { at: B.deceive, voice: "gymbro-deceive", rate: 1.1 },
    { at: B.moo, moo: "alarmed", gain: 1.0 },
    { at: B.moo + 0.05, sound: "sonicBoom", gain: 0.9 },
    { at: B.launch, sound: "launch", gain: 0.8 },
    { at: B.star, sound: "twinkle", gain: 0.6 },
    { at: B.receipt, sound: "printer", gain: 0.5 },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: null, fog: ["#c77a6a", 30, 90] });
  const sky = skyDome("#2e2a6b", "#ff9a5a", { horizon: -0.02 });
  scene.add(sky);
  lights(scene, { dir: [-8, 4, 6], color: "#ffb27a", intensity: 2.2, sky: "#8f86ff", groundColor: "#a86a5a", hemi: 0.8, ambient: 0.2, box: 10 });
  scene.add(ground(120, P.snow, { seed: "gym" }));
  const gym = building(10, 5, 5, "#3a3f4b", { seed: 4, lit: 0.8, windowColor: "#ffe2a8" });
  gym.position.set(0, 0, -9);
  scene.add(gym);
  const sign = neon(segment.text.gym, P.pink, { w: 3.2, h: 1.2 });
  sign.position.set(-1.5, 3.0, -6.3);
  scene.add(sign);
  const signGlow = glowSprite(P.pink, 6, 0.7);
  signGlow.position.set(-1.5, 3.0, -6.1);
  scene.add(signGlow);
  for (let i = 0; i < 9; i++) {
    const p = pine(4 + (i % 3), { seed: i });
    p.position.set(-14 + i * 3.5, 0, -15 - (i % 2) * 3);
    scene.add(p);
  }
  for (const [x, z] of [[-4.5, -2], [4.5, -3]]) {
    const b = snowbank(3, { seed: x });
    b.position.set(x, 0, z);
    scene.add(b);
  }
  const lp = lamp(4.5);
  lp.position.set(3.4, 0, -2.5);
  scene.add(lp);
  const snow = snowfall({ count: 500, seed: "gym-snow", x: [-10, 10], y: [0, 12], z: [-12, 6], speed: [0.6, 1.1] });
  scene.add(snow.object);

  const bro = makePerson({ tank: "#e53935", shirt: "#e53935", pants: "#8b8f99", sunglasses: true, chain: true, hair: "spiky", hairColor: P.hair.black, skin: P.skin[2] });
  bro.root.position.set(-0.95, 0, 0.6);
  bro.root.rotation.y = 0.35;
  scene.add(bro.root);
  const heart = glowSprite("#ff4f8b", 1.4, 0);
  scene.add(heart);
  const aura = auraWedge(1.3);
  scene.add(aura);

  // the dream tower of PROfeel cups behind him
  const tower = new THREE.Group();
  let n = 0;
  for (let row = 0; row < 5; row++) {
    for (let i = 0; i < 5 - row; i++) {
      const c = tub(segment.text.cups, { body: P.profeel, lid: [P.pink, P.lime, P.yellow][n++ % 3], s: 1.4 });
      c.position.set((i - (4 - row) / 2) * 0.66, row * 0.5, 0);
      tower.add(c);
    }
  }
  tower.position.set(-2.4, 0, -1.8);
  tower.rotation.y = 0.3;
  scene.add(tower);

  const cow = makeCow();
  cow.root.position.set(1.05, 0, 0.3);
  cow.root.rotation.y = -0.4;
  scene.add(cow.root);
  const boom = ring("#ffffff", { inner: 0.85, outer: 1 });
  scene.add(boom.object);
  const boom2 = ring(P.pink, { inner: 0.9, outer: 1 });
  scene.add(boom2.object);

  // the launch: a parabola up and away
  const launchPos = (tt) => {
    const tau = Math.max(0, tt - B.launch);
    return [-0.95 - 2.5 * tau, 0.0 + 16 * tau - 1.5 * tau * tau, 0.6 - 9 * tau];
  };
  const camPos = track([[0, [0.1, 2.7, 9.8]], [B.deceive, [0.05, 2.65, 9.0], "linear"], [B.deceive + 0.12, [-0.5, 2.6, 6.4], "outQuart"], [B.moo, [-0.5, 2.6, 6.2], "linear"], [B.moo + 0.05, [0.1, 2.8, 10.0], "outQuart"], [5.6, [0.1, 2.3, 10.4], "linear"]]);
  const camTgt = track([[0, [0.05, 1.95, 0.3]], [B.deceive + 0.12, [-0.75, 2.3, 0.6], "outQuart"], [B.moo + 0.05, [0.05, 2.1, 0.3], "outQuart"], [B.launch + 0.1, [0.0, 2.6, 0], "linear"], [B.star, [-1.8, 8.5, -6], "inOutCubic"]]);

  const tip = new THREE.Vector3();

  return {
    scene,
    camera,
    update(t) {
      snow.update(t, 0.3);
      look(camera, camPos(t), camTgt(t), { shake: shake(t, B.moo + 0.05, { amp: 0.25, dur: 0.6, seed: 4 }) });
      // the bro: bicep heart, ask, lean in, launch
      let pose = POSES.bicepHeart;
      pose = mixPose(pose, POSES.lean, ease(t, B.deceive - 0.15, B.deceive + 0.05));
      pose = mixPose(pose, POSES.flail, ease(t, B.launch, B.launch + 0.15));
      bro.pose(pose);
      const talking = (t > B.ask && t < B.ask + 2.3) || (t > B.deceive && t < B.deceive + 1.25);
      bro.talk(talking ? Math.max(0, noise1(t * 13, 8) * 0.5 + 0.4) : 0);
      // sunglasses slide down to show wide eyes
      const glasses = ease(t, B.deceive - 0.1, B.deceive + 0.05);
      bro.shades.position.y = 0.5 - 0.24 * glasses;
      bro.eyes(1 + 0.6 * glasses);
      bro.brows(-0.25 * glasses, 0.08 * glasses);
      const lp0 = launchPos(t);
      if (t > B.launch) {
        bro.root.position.set(lp0[0], lp0[1], lp0[2]);
        bro.root.rotation.set((t - B.launch) * 9, 0.35, (t - B.launch) * 5);
      } else {
        bro.root.position.set(-0.95, 0, 0.6);
        bro.root.rotation.set(0, 0.35, 0);
      }
      bro.root.visible = t < B.star;
      aura.visible = t > B.launch && t < B.star;
      if (t > B.launch) aura.position.set(lp0[0] + 0.9, lp0[1] + 1.2, lp0[2] + 0.4);
      else aura.position.set(-0.3, 0.0, 1.6);
      aura.rotation.set(t * 2, t * 3, 0);

      // heart between his hands
      bro.handR.getWorldPosition(tip);
      heart.position.set(tip.x + 0.1, tip.y + 0.2, tip.z + 0.3);
      heart.material.opacity = 0.9 * (1 - ease(t, B.deceive - 0.2, B.deceive)) * (t > 0.3 ? 1 : 0);
      heart.scale.setScalar(1.2 + 0.2 * Math.sin(t * 10));
      // the dream tower
      tower.scale.setScalar(Math.max(0.001, pop(t, B.ask + 0.3, 0.35) * (1 - seg(t, B.moo, B.moo + 0.15))));
      // Mansikki
      const m = bump(t, B.moo, B.moo + 0.7);
      cow.moo(m);
      cow.pose(mixPose(POSES.idle, POSES.wide, m));
      cow.eyes(1 + 0.5 * m);
      cow.brows(-0.35 * m, 0.08 * m);
      cow.head.rotation.y = 0.25 * ease(t, B.deceive, B.deceive + 0.2) * (1 - m);
      cow.wag(t);
      boom.update(t, B.moo + 0.05, camera, { dur: 0.6, size: 7 });
      boom2.update(t, B.moo + 0.15, camera, { dur: 0.6, size: 5 });
      boom.object.position.set(1.05, 3.0, 0.8);
      boom2.object.position.set(1.05, 3.0, 0.8);
    },
    overlay(g, t) {
      speedLines(g, t, bump(t, B.moo, B.moo + 0.5), { cx: 640, cy: 760 });
      // his lines
      if (t > B.ask && t < B.deceive) {
        const words = segment.text.ask.split(" ");
        const nw = Math.min(words.length, 1 + Math.floor(((t - B.ask) / 2.2) * words.length));
        caption(g, words.slice(0, nw).join(" "), 540, 1330, 1, { size: 62, maxW: 880 });
      }
      caption(g, segment.text.deceive, 540, 1360, pop(t, B.deceive + 0.05, 0.2) * (t < B.moo ? 1 : 0), { size: 70, fill: P.yellow });
      cowCaption(g, segment.text.cow, 1360, pop(t, B.moo + 0.1, 0.3) * (1 - seg(t, B.star - 0.1, B.star)), { moo: "MOOOO!", mood: "alarmed" });
      // he becomes a star
      if (t > B.star - 0.05) {
        const lp = launchPos(B.star);
        const [sx, sy] = toScreen(camera, lp[0], lp[1], lp[2]);
        sparkle(g, sx, sy, t, B.star, { size: 120, dur: 0.5 });
        g.save();
        g.fillStyle = "#ffffff";
        g.beginPath();
        g.arc(sx, sy, 8 + 2 * Math.sin(t * 20), 0, Math.PI * 2);
        g.fill();
        g.restore();
        outlined(g, segment.text.aura, 540, 1080, { size: 150, scale: pop(t, B.star + 0.05, 0.25), fill: P.red, rot: -0.06, lw: 24 });
      }
      // the receipt
      const rk = E.outBack(seg(t, B.receipt, B.receipt + 0.3));
      if (t > B.receipt) {
        g.save();
        g.translate(540, 1420 + (1 - rk) * 300);
        g.rotate(0.04);
        brutal(g, -260, -60, 520, 120, { fill: "#ffffff", r: 6, bw: 4, shadow: 6 });
        g.fillStyle = P.ink;
        g.font = `700 32px ${UI}`;
        g.textAlign = "center";
        g.textBaseline = "middle";
        g.fillText(`🧾 ${segment.text.receipt}`, 0, 2);
        g.restore();
      }
    },
  };
}

