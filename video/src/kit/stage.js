/** Scene and camera boilerplate, and camera moves from keyframe tracks. */
import * as THREE from "three";
import { H, W } from "../timeline.js";

export function stage({ background = "#000000", fog = null, fov = 50, far = 1000 } = {}) {
  const scene = new THREE.Scene();
  if (background) scene.background = new THREE.Color(background);
  if (fog) scene.fog = new THREE.Fog(fog[0], fog[1], fog[2]);
  const camera = new THREE.PerspectiveCamera(fov, W / H, 0.1, far);
  return { scene, camera };
}

/** Places the camera at pos looking at target, with an optional roll and shake offset [dx, dy, roll]. */
export function look(camera, pos, target, { roll = 0, shake = [0, 0, 0], fov = null } = {}) {
  camera.position.set(pos[0] + shake[0], pos[1] + shake[1], pos[2]);
  camera.up.set(0, 1, 0);
  camera.lookAt(target[0] + shake[0], target[1] + shake[1], target[2]);
  if (roll || shake[2]) camera.rotateZ(roll + shake[2]);
  if (fov && camera.fov !== fov) {
    camera.fov = fov;
    camera.updateProjectionMatrix();
  }
}

/**
 * Shots: [[from, posTrack, targetTrack, fovTrack?], …] — the shot whose `from` is the latest before t is used,
 * with its tracks read at t (hard cuts between shots).
 */
export function shots(list) {
  return (t) => {
    let s = list[0];
    for (const x of list) if (t >= x[0]) s = x;
    const fov = s[3] ? (typeof s[3] === "function" ? s[3](t) : s[3]) : 50;
    return { pos: s[1](t), target: s[2](t), fov, index: list.indexOf(s) };
  };
}

/** Projects a world point to output-canvas pixels (for 2D text that follows a 3D thing). */
export function toScreen(camera, x, y, z) {
  const v = new THREE.Vector3(x, y, z).project(camera);
  return [((v.x + 1) / 2) * W, ((1 - v.y) / 2) * H, v.z];
}
