/**
 * 1 L · SHE GETS ME: an exchange student at 3 AM, an empty fridge, terrible Finnish. Talk to order, FI or EN.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.86  he stares into the empty fridge, phone up
 * 0.95  "laktoo… LAKTOOSITON MAITO??" (voice, word by word)
 * 2.85  poof: Mansikki pops out of the phone in her headset
 * 3.05  her moo; the caption card carries her words
 * 3.60  an Eila carton drops into the fridge; ding; the fridge light flashes
 * 4.00  snap zoom on him: "bro understood my Finnish 😭" (whisper)
 */
import * as THREE from "three";
import { makeCow } from "../kit/cow.js";
import { bump, E, ease, pop, seg, track } from "../kit/ease.js";
import { burst, drop, glowSprite, shake, snowfall, sparkle } from "../kit/fx.js";
import { box, flat } from "../kit/mat.js";
import { P } from "../kit/palette.js";
import { makePerson, makePhone, mixPose, POSES } from "../kit/person.js";
import { carton, fridge as makeFridge, laptop, table } from "../kit/props.js";
import { noise1 } from "../kit/rand.js";
import { look, stage, toScreen } from "../kit/stage.js";
import { boxCaption, caption, cowCaption } from "../kit/text2d.js";
import { lights, room, windowPane } from "../kit/world.js";

const B = { stare: 0.86, ask: 0.95, askEnd: 2.8, poof: 2.85, moo: 3.05, drop: 3.6, zoom: 4.0 };

export function sounds() {
  return [
    { music: "lofi", from: 0.86, rests: [[2.8, 3.1], [4.0, 5.6]] },
    { at: 0.9, sound: "hum", gain: 0.25, dur: 4.6 },
    { at: B.ask, voice: "fridge-student", rate: 1.1 },
    { at: B.poof, sound: "poof", gain: 0.8 },
    { at: B.poof + 0.05, sound: "twinkle", gain: 0.5 },
    { at: B.moo, moo: "happy", gain: 0.8 },
    { at: B.drop + 0.3, sound: "ding", gain: 0.7 },
    { at: B.zoom, sound: "zoom", gain: 0.6 },
    { at: B.zoom + 0.05, voice: "fridge-whisper", rate: 1.15 },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: "#141a33", fog: ["#141a33", 14, 30] });
  lights(scene, { dir: [-6, 7, 5], color: "#8fa8ff", intensity: 0.9, sky: "#5468b8", groundColor: "#2a2030", hemi: 0.75, ambient: 0.18, box: 8 });

  const rm = room(9, 5.5, 16, { wall: "#3c4670", floor: "#8a6a4a", side: "#343d63", trim: "#2b3254" });
  rm.position.z = 4.5;
  scene.add(rm);
  const win = windowPane(1.9, 2.0, { sky: "#1d2c66", frame: "#d9dde8" });
  win.position.set(-2.2, 2.9, -3.38);
  scene.add(win);
  const flakes = snowfall({ count: 120, seed: "fridge-window", x: [-3.1, -1.3], y: [1.95, 3.85], z: [-3.3, -3.25], speed: [0.4, 0.8], size: 0.06, sway: 0.08 });
  scene.add(flakes.object);
  // a poster and a tiny desk with a laptop
  const poster = box(1.2, 1.6, 0.04, P.pink, 0.2, 3.2, -3.38);
  scene.add(poster, box(0.8, 0.5, 0.05, P.yellow, 0.2, 3.5, -3.35));
  const desk = table(1.8, 1, 1.2, { top: "#d8c9b0", legs: "#5a4a3a" });
  desk.position.set(-3.1, 0, -2.3);
  scene.add(desk);
  const lap = laptop("#6fd3ff");
  lap.position.set(-3.1, 1.26, -2.3);
  scene.add(lap);

  const fr = makeFridge();
  fr.position.set(2.4, 0, -1.7);
  fr.rotation.y = -0.35;
  scene.add(fr);
  const fridgeLight = new THREE.PointLight("#dff2ff", 16, 7, 1.6);
  fridgeLight.position.set(2.3, 2.0, -0.9);
  scene.add(fridgeLight);
  const milk = carton(segment.text.carton, { color: P.eila, s: 1.1 });
  milk.position.set(0, 0, 0);
  const milkHolder = new THREE.Group();
  milkHolder.position.set(2.4, 0, -1.75);
  milkHolder.rotation.y = -0.35;
  milkHolder.add(milk);
  scene.add(milkHolder);

  const student = makePerson({ shirt: "#6b7a8f", hoodie: "#6b7a8f", pants: "#2d3340", beanie: "#e0603a", hair: "short", hairColor: P.hair.blond, skin: P.skin[4], tired: true });
  student.root.position.set(0.75, 0, 0.5);
  scene.add(student.root);
  const ph = makePhone("#fff4dc");
  student.hold(ph, "R", 0, -0.62, 0.12);
  ph.rotation.x = -1.4;

  const cow = makeCow();
  cow.root.position.set(-0.95, 0, 0.8);
  cow.root.rotation.y = 0.45;
  scene.add(cow.root);
  const puff = burst({
    count: 18,
    seed: "fridge-puff",
    origin: [0.1, 1.6, 1.0],
    at: B.poof,
    speed: [2.5, 4.5],
    dir: [-0.3, 0.2, 0.2],
    spread: 1.4,
    gravity: 0.5,
    floor: -10,
    life: 0.4,
    make: () => new THREE.Mesh(new THREE.IcosahedronGeometry(0.14, 0), flat("#ffffff")),
  });
  scene.add(puff.object);
  const cowGlow = glowSprite(P.pink, 4, 0.0);
  cowGlow.position.set(-1.0, 2.0, 0.9);
  scene.add(cowGlow);

  const camPos = track([[0, [0.2, 2.9, 10.4]], [B.poof, [0.2, 2.8, 9.3], "linear"], [B.poof + 0.4, [-0.2, 2.9, 10.2], "outCubic"], [B.zoom, [-0.2, 2.85, 9.8], "linear"]]);
  const camTgt = track([[0, [0.8, 1.75, -0.2]], [B.poof, [0.75, 1.7, -0.1], "linear"], [B.poof + 0.4, [0.05, 1.75, 0], "outCubic"]]);
  const zoomPos = track([[B.zoom, [0.5, 2.6, 6.4]], [B.zoom + 0.18, [0.5, 2.5, 5.3], "outQuart"], [5.6, [0.5, 2.5, 5.0], "linear"]]);

  return {
    scene,
    camera,
    update(t) {
      flakes.update(t);
      fr.userData.door.rotation.y = 1.9;
      // camera: slow push, then a snap zoom on the whisper
      if (t < B.zoom) look(camera, camPos(t), camTgt(t), { shake: shake(t, B.poof, { amp: 0.06, dur: 0.3 }) });
      else look(camera, zoomPos(t), [0.6, 2.2, 0.5], { fov: 40 });
      if (t < B.zoom && camera.fov !== 50) {
        camera.fov = 50;
        camera.updateProjectionMatrix();
      }

      // student: staring into the fridge, phone up, then turns to camera
      const turn = ease(t, B.zoom - 0.15, B.zoom + 0.1, "outCubic");
      student.root.rotation.y = 0.75 - 0.75 * turn;
      student.pose(mixPose(POSES.phone, POSES.phoneLow, ease(t, B.poof, B.poof + 0.3) * (1 - turn)));
      const talking = t > B.ask && t < B.askEnd ? Math.max(0, noise1(t * 12, 1) * 0.6 + 0.4) : 0;
      const whisper = t > B.zoom + 0.05 && t < 5.45 ? Math.max(0, noise1(t * 10, 4) * 0.3 + 0.25) : 0;
      student.talk(talking + whisper);
      student.eyes(1 + 0.5 * ease(t, B.poof, B.poof + 0.15) - 0.2 * turn);
      student.brows(-0.25 * ease(t, B.poof, B.poof + 0.1), 0.06 * ease(t, B.poof, B.poof + 0.1));
      student.blink(t > 2.0 && t < 2.08 ? 1 : 0);
      student.root.position.x = 0.75 + 0.12 * bump(t, B.poof, B.poof + 0.5);

      // cow pops out of the phone and grows
      const g0 = pop(t, B.poof, 0.4);
      cow.root.visible = t >= B.poof;
      cow.root.scale.setScalar(Math.max(0.001, g0));
      const fly = E.outCubic(seg(t, B.poof, B.poof + 0.35));
      cow.root.position.set(0.45 + (-0.95 - 0.45) * fly, 1.9 * (1 - fly), 1.0 - 0.2 * fly);
      const m = bump(t, B.moo, B.moo + 0.55);
      cow.moo(m);
      cow.pose(mixPose(POSES.idle, POSES.wide, m * 0.4 + 0.15));
      cow.wag(t);
      cow.blink(t > 4.0 && t < 4.08 ? 1 : 0);
      cowGlow.material.opacity = 0.8 * bump(t, B.poof, B.poof + 0.6);
      puff.update(t);

      // the carton falls onto the middle shelf
      const d = drop(t, B.drop, 6.5, 1.72, 26, 0.2);
      milk.position.y = d.y;
      milk.visible = t >= B.drop;
      milk.rotation.y = d.falling ? (t - B.drop) * 8 : 0.3;
      fridgeLight.intensity = 16 + 30 * bump(t, d.tLand, d.tLand + 0.35);
    },
    overlay(g, t) {
      // his line, word by word
      if (t > B.ask && t < B.zoom) {
        const words = segment.text.ask.split(" ");
        const n = Math.min(words.length, 1 + Math.floor(((t - B.ask) / (B.askEnd - B.ask)) * words.length));
        const shown = words.slice(0, n).join(" ");
        caption(g, shown, 540, 1300, 1, { size: 64, alpha: 1 - seg(t, B.poof, B.poof + 0.15) });
      }
      // her caption card
      const ck = pop(t, B.moo, 0.3) * (1 - seg(t, B.zoom - 0.1, B.zoom));
      cowCaption(g, segment.text.cow, 1330, ck);
      // the carton lands: sparkle at its spot
      const [sx, sy] = toScreen(camera, 2.4, 2.4, -1.75);
      sparkle(g, sx, sy, t, B.drop + 0.32, { size: 80 });
      // the whisper
      boxCaption(g, segment.text.whisper, 540, 1380, pop(t, B.zoom + 0.1, 0.25), { size: 50 });
    },
  };
}
