/**
 * End card: Mansikki in front of the Milky Way; a dolly zoom; her eyes glint.
 * "The Embassy of Finland was closed on November 10th. Mansikki wasn't." (the Embassy meme, Nov 2026)
 *
 * Beats (local s):
 * 0.15  the Embassy line types in
 * 1.30  "Mansikki wasn't." · her eyes glint · a slow moo
 * 2.20  the name and Junction 2026
 */
import { makeCow } from "../kit/cow.js";
import { E, pop, seg, typed } from "../kit/ease.js";
import { glowSprite, grain, sparkle, vignette } from "../kit/fx.js";
import { P } from "../kit/palette.js";
import { POSES } from "../kit/person.js";
import { makeGalaxy } from "../kit/space.js";
import { look, stage, toScreen } from "../kit/stage.js";
import { outlined } from "../kit/text2d.js";
import { lights, stars } from "../kit/world.js";

const B = { embassy: 0.15, wasnt: 1.3, glint: 1.35, name: 2.2 };

export function sounds() {
  return [
    { music: "eerie", from: 0, rests: [] },
    { at: 0.0, sound: "drone", gain: 0.5, dur: 3.6 },
    { at: B.wasnt, moo: "greet", gain: 0.5, rate: 0.8 },
    { at: B.glint, sound: "twinkle", gain: 0.7 },
    { at: B.name, sound: "boom", gain: 0.5 },
  ];
}

export function build(segment) {
  const text = segment.text;
  const { scene, camera } = stage({ background: "#03040c", far: 2000 });
  scene.add(stars(1600, "end-stars", 600, { minY: -1, size: 2.0 }));
  lights(scene, { dir: [4, 5, 10], color: "#e6ebff", intensity: 1.8, sky: "#8fa0ff", groundColor: "#20103a", hemi: 0.9, ambient: 0.3 });
  const gal = makeGalaxy({ N: 5000, R: 16, seed: "end-galaxy" });
  gal.object.position.set(0, 4, -40);
  gal.object.rotation.x = 1.15;
  scene.add(gal.object);
  const core = glowSprite("#fff4dc", 14, 0.7);
  core.position.set(0, 4, -40);
  scene.add(core);
  const cow = makeCow();
  cow.pose(POSES.idle);
  scene.add(cow.root);
  const glints = [cow.face.eyeL, cow.face.eyeR];

  return {
    scene,
    camera,
    update(t) {
      // dolly zoom: move in while the lens widens, so she keeps her size and space stretches behind her
      const k = E.inOutQuad(seg(t, 0, 3.6));
      const d = 7.5 - 4.3 * k;
      const fov = (2 * Math.atan(2.1 / d) * 180) / Math.PI;
      look(camera, [0, 2.6, d], [0, 2.3, 0], { fov });
      gal.update(t + 5, 1);
      cow.head.rotation.y = -0.25 + 0.25 * E.inOutCubic(seg(t, 0.4, 1.2));
      cow.blink(t > 0.9 && t < 1.0 ? 1 : 0);
      for (const e of glints) e.scale.setScalar(1 + 0.15 * Math.sin(Math.PI * seg(t, B.glint, B.glint + 0.5)));
    },
    overlay(g, t) {
      vignette(g, 0.65);
      const l1 = typed(text.embassy[0], t, B.embassy, 40);
      const l2 = typed(text.embassy[1], t, B.embassy + text.embassy[0].length / 40, 40);
      outlined(g, l1, 540, 1180, { size: 54, lw: 10, shadow: false });
      outlined(g, l2, 540, 1250, { size: 54, lw: 10, shadow: false });
      outlined(g, text.wasnt, 540, 1390, { size: 104, scale: pop(t, B.wasnt, 0.3), fill: P.pink, lw: 20 });
      const [ex, ey] = toScreen(camera, 0.22, 2.67 + 0.12, 0.47);
      const [fx, fy] = toScreen(camera, -0.22, 2.67 + 0.12, 0.47);
      sparkle(g, ex, ey, t, B.glint, { size: 70 });
      sparkle(g, fx, fy, t, B.glint + 0.08, { size: 70 });
      outlined(g, text.name, 540, 300, { size: 78, scale: pop(t, B.name, 0.3), fill: P.yellow, lw: 16 });
      outlined(g, text.event, 540, 390, { size: 52, scale: pop(t, B.name + 0.15, 0.3), lw: 10 });
      grain(g, t, 0.12);
    },
  };
}
