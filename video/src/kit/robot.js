/**
 * A clanker: a grey boxy robot (another AI agent). Same joints as the person; a screen face drawn on a
 * live canvas texture, and an antenna that can droop. Feet at y = 0, about 2.6 units tall.
 */
import * as THREE from "three";
import { P } from "./palette.js";
import { box, cyl, flat, glow, pivot } from "./mat.js";
import { applyPose, POSES } from "./person.js";
import { liveTexture } from "./world.js";

export function makeRobot({ color = "#8d96a3", accent = P.cyan, face = "eyes", seed = 0 } = {}) {
  const root = new THREE.Group();
  const body = flat(color);
  const dark = flat("#4a5260");

  const legs = {};
  for (const [side, x] of [["L", 0.26], ["R", -0.26]]) {
    const knee = pivot(0, -0.45, 0, box(0.3, 0.45, 0.3, dark, 0, -0.22, 0), box(0.42, 0.16, 0.52, body, 0, -0.45, 0.05));
    const hip = pivot(x, 0.95, 0, box(0.32, 0.5, 0.32, body, 0, -0.23, 0), knee);
    legs[side] = { hip, knee };
    root.add(hip);
  }
  const spine = pivot(0, 0.95, 0);
  root.add(spine);
  spine.add(box(1.05, 1.0, 0.7, body, 0, 0.5, 0));
  spine.add(box(0.6, 0.4, 0.04, dark, 0, 0.55, 0.36));
  const lights = [];
  for (let i = 0; i < 3; i++) {
    const l = box(0.1, 0.1, 0.03, [P.red, P.yellow, P.lime][i], -0.18 + i * 0.18, 0.55, 0.39);
    l.material = glow([P.red, P.yellow, P.lime][i]);
    lights.push(l);
    spine.add(l);
  }

  const neck = pivot(0, 1.05, 0);
  spine.add(neck);
  neck.add(cyl(0.12, 0.14, 0.18, 6, dark, 0, 0.05, 0));
  const head = new THREE.Group();
  head.position.y = 0.48;
  neck.add(head);
  head.add(box(0.95, 0.7, 0.72, body, 0, 0, 0));
  head.add(box(0.12, 0.3, 0.3, dark, 0.53, 0, 0), box(0.12, 0.3, 0.3, dark, -0.53, 0, 0));
  const screenTex = liveTexture(256, 160, (g, s) => {
    g.fillStyle = "#0b1a22";
    g.fillRect(0, 0, 256, 160);
    g.fillStyle = accent;
    g.strokeStyle = accent;
    g.lineWidth = 10;
    if (s.face === "eyes") {
      g.fillRect(58, 50, 40, 52);
      g.fillRect(158, 50, 40, 52);
    } else if (s.face === "sad") {
      g.beginPath();
      g.moveTo(50, 70);
      g.lineTo(100, 90);
      g.moveTo(206, 70);
      g.lineTo(156, 90);
      g.stroke();
      g.fillRect(70, 100, 20, 20);
      g.fillRect(166, 100, 20, 20);
    } else if (s.face === "x") {
      for (const cx of [78, 178]) {
        g.beginPath();
        g.moveTo(cx - 22, 52);
        g.lineTo(cx + 22, 104);
        g.moveTo(cx + 22, 52);
        g.lineTo(cx - 22, 104);
        g.stroke();
      }
    } else if (s.face === "sly") {
      g.fillRect(52, 72, 52, 16);
      g.fillRect(152, 72, 52, 16);
      g.fillRect(96, 118, 64, 8);
    } else {
      g.font = "bold 34px 'Space Grotesk', sans-serif";
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.fillText(s.face, 128, 80);
    }
  }, { face });
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.78, 0.5), new THREE.MeshBasicMaterial({ map: screenTex.texture, toneMapped: false }));
  screen.position.z = 0.365;
  head.add(screen);
  const antenna = pivot(0, 0.35, 0, cyl(0.025, 0.025, 0.45, 4, dark, 0, 0.22, 0));
  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.08, 6, 4), glow(P.red));
  ball.position.y = 0.48;
  antenna.add(ball);
  head.add(antenna);

  const arms = {};
  for (const [side, x] of [["L", 0.66], ["R", -0.66]]) {
    const claw = new THREE.Group();
    claw.position.y = -0.48;
    claw.add(box(0.26, 0.12, 0.26, dark, 0, 0, 0), box(0.06, 0.18, 0.2, dark, 0.09, -0.12, 0), box(0.06, 0.18, 0.2, dark, -0.09, -0.12, 0));
    const el = pivot(0, -0.46, 0, cyl(0.1, 0.1, 0.44, 6, body, 0, -0.22, 0), claw);
    const sh = pivot(x, 0.9, 0, cyl(0.12, 0.12, 0.5, 6, body, 0, -0.22, 0), el);
    spine.add(sh);
    arms[side] = { sh, el, claw };
  }

  const j = {
    spine,
    neck,
    shL: arms.L.sh,
    elL: arms.L.el,
    shR: arms.R.sh,
    elR: arms.R.el,
    hipL: legs.L.hip,
    hipR: legs.R.hip,
    kneeL: legs.L.knee,
    kneeR: legs.R.knee,
  };
  const api = {
    root,
    j,
    head,
    antenna,
    lights,
    seed,
    pose(p) {
      applyPose(j, p);
      return api;
    },
    face(f) {
      screenTex.set({ face: f });
      return api;
    },
    droop(k) {
      antenna.rotation.z = 1.4 * k;
      antenna.rotation.x = 0.4 * k;
      return api;
    },
    hold(mesh, side = "R", x = 0, y = -0.66, z = 0.1) {
      mesh.position.set(x, y, z);
      (side === "R" ? arms.R.el : arms.L.el).add(mesh);
      return mesh;
    },
  };
  api.pose(POSES.idle);
  return api;
}
