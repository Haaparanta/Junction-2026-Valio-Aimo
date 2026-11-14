/**
 * MILKY WAY: someone ordered too much. The milk streams up and swirls into the Milky Way. Mansikki floats in
 * her headset; the gym bro twinkles nearby as a star. The limit still holds.
 *
 * Beats (local s; the title card covers 0–0.86):
 * 0.86  the milk streams up from below and swirls into a galaxy
 * 1.00  narrator (eerie): "And her limit? Still five hundred euros."
 * 2.40  her caption card: "1,000,000,000 L · still needs your manager"
 * 3.10  the gym bro's star twinkles: "−∞ AURA", the AURA wedge drifting by
 */
import { makeCow } from "../kit/cow.js";
import { ease, pop, seg, track } from "../kit/ease.js";
import { glowSprite, sparkle, vignette } from "../kit/fx.js";
import { P } from "../kit/palette.js";
import { mixPose, POSES } from "../kit/person.js";
import { auraWedge } from "../kit/props.js";
import { makeGalaxy } from "../kit/space.js";
import { look, stage, toScreen } from "../kit/stage.js";
import { cowCaption, outlined } from "../kit/text2d.js";
import { lights, stars } from "../kit/world.js";

const B = { form: 0.86, narrator: 1.0, caption: 2.4, star: 3.1 };

export function sounds() {
  return [
    { music: "eerie", from: 0.86, rests: [] },
    { at: B.form, sound: "swirl", gain: 0.7 },
    { at: B.narrator, voice: "galaxy-narrator", rate: 1.0, room: "hall" },
    { at: B.caption, moo: "greet", gain: 0.45, rate: 0.85 },
    { at: B.star, sound: "twinkle", gain: 0.6 },
  ];
}

export function build(segment) {
  const { scene, camera } = stage({ background: "#03040c", far: 2000 });
  scene.add(stars(1600, "space-stars", 600, { minY: -1, size: 2.0 }));
  lights(scene, { dir: [6, 6, 10], color: "#dfe6ff", intensity: 1.6, sky: "#8fa0ff", groundColor: "#20103a", hemi: 0.8, ambient: 0.3 });
  const gal = makeGalaxy({ N: 6000, R: 16, from: [0, -45, 0] });
  gal.object.position.set(0, 7, -34);
  gal.object.rotation.x = 1.05;
  scene.add(gal.object);
  const core = glowSprite("#fff4dc", 12, 0);
  core.position.set(0, 7, -34);
  scene.add(core);

  const cow = makeCow();
  cow.root.position.set(0.4, -0.9, 3.2);
  scene.add(cow.root);
  const star = glowSprite("#ffffff", 1.6, 0);
  star.position.set(-4.2, 7.0, -10);
  scene.add(star);
  const aura = auraWedge(1.2);
  aura.position.set(-2.6, 4.6, -4);
  scene.add(aura);

  const cam = track([[0, [0, 2.2, 11.5]], [5, [0.4, 2.0, 10.2], "linear"]]);

  return {
    scene,
    camera,
    update(t) {
      look(camera, cam(t), [0, 2.6, -6], { roll: 0.04 * Math.sin(t * 0.8) });
      const form = seg(t, B.form, 3.2);
      gal.update(t, form);
      core.material.opacity = 0.8 * ease(t, 1.6, 2.8);
      // Mansikki floats, turning slowly
      cow.pose(mixPose(POSES.wide, POSES.armsUp, 0.3 + 0.2 * Math.sin(t * 1.3)));
      cow.root.rotation.set(0.15 * Math.sin(t * 0.9), -0.35 + 0.25 * Math.sin(t * 0.6), 0.1 * Math.sin(t * 1.1));
      cow.root.position.y = -0.9 + 0.15 * Math.sin(t * 1.4);
      cow.blink(t > 3.4 && t < 3.5 ? 1 : 0);
      cow.wag(t * 0.5);
      star.material.opacity = t > B.star ? 0.9 + 0.1 * Math.sin(t * 25) : 0;
      star.scale.setScalar(1.6 + 0.6 * Math.sin(t * 9));
      aura.rotation.set(t * 0.7, t * 1.1, 0.3);
      aura.position.set(-2.6 + 0.3 * t, 4.6 - 0.1 * t, -4);
    },
    overlay(g, t) {
      vignette(g, 0.45);
      if (t > B.star) {
        const [sx, sy] = toScreen(camera, -4.2, 7.0, -10);
        sparkle(g, sx, sy, t, B.star, { size: 90 });
        outlined(g, segment.text.star, sx + 10, sy + 70, { size: 46, scale: pop(t, B.star + 0.1, 0.25), fill: P.red, lw: 10 });
      }
      cowCaption(g, segment.text.cow, 1420, pop(t, B.caption, 0.3), { moo: "moo.", mood: "happy" });
    },
  };
}
