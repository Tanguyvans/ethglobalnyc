/**
 * TSL (Three Shading Language) node materials for the WebGPU slice.
 * All imports come from `three/tsl` (re-export of the three.webgpu bundle).
 *
 * These are the WebGPU replacements for what the WebGL app does with
 * GLSL `onBeforeCompile` patches / drei materials.
 */
import {
  Fn,
  vec3,
  vec4,
  float,
  uniform,
  color,
  mix,
  smoothstep,
  clamp,
  positionLocal,
  positionWorld,
  normalLocal,
  normalWorld,
  attribute,
  mx_noise_float,
  // r0.169 exposes the elapsed-time node as `timerLocal` (renamed to `time`
  // in later three versions). Aliased to `time` so the shader code reads clean.
  timerLocal as time,
  uv,
  dot,
  abs,
} from 'three/tsl'
import {
  MeshStandardNodeMaterial,
  MeshBasicNodeMaterial,
  DoubleSide,
} from 'three/webgpu'
import { Color } from 'three'

const PAL = {
  sky: new Color('#9fd0ff'),
  skyHigh: new Color('#5aa9f0'),
  horizon: new Color('#dcefff'),
  water: new Color('#2f6fb0'),
  waterDeep: new Color('#1c4a7d'),
  sand: new Color('#d8c79c'),
  grass: new Color('#4f8f3c'),
  grassDark: new Color('#3a6e2b'),
  rock: new Color('#7c756b'),
  snow: new Color('#eef3f8'),
}

/** ---- Procedural terrain height shared by CPU? No — fully GPU here. ---- */

/** fbm noise in TSL (3 octaves of mx_noise_float). */
const fbm = /*#__PURE__*/ Fn(([p]: any) => {
  const n = float(0).toVar()
  const amp = float(0.5).toVar()
  const freq = float(1.0).toVar()
  // unrolled octaves (TSL Loop also exists, but unrolling is simplest)
  for (let i = 0; i < 4; i++) {
    n.addAssign(mx_noise_float(p.mul(freq)).mul(amp))
    amp.mulAssign(0.5)
    freq.mulAssign(2.0)
  }
  return n
})

export const TERRAIN_AMPLITUDE = 6.0
export const TERRAIN_SCALE = 0.06

/**
 * Terrain material: GPU vertex displacement via positionNode + slope-blended
 * albedo via colorNode. Uses MeshStandardNodeMaterial so it still responds to
 * the directional light + ambient (atmospheric look, no black shadows).
 */
export function makeTerrainMaterial() {
  const amp = uniform(TERRAIN_AMPLITUDE)
  const scl = uniform(TERRAIN_SCALE)

  // Height field as a function of world-ish XZ.
  const heightAt = Fn(([xz]: any) => fbm(vec3(xz.x.mul(scl), xz.y.mul(scl), float(0))).mul(amp))

  const mat = new MeshStandardNodeMaterial()
  mat.metalness = 0.0
  mat.roughness = 0.95

  // Displace along local Y (plane is rotated -90deg X so local XY -> world XZ).
  const h = heightAt(positionLocal.xy)
  mat.positionNode = vec3(positionLocal.x, positionLocal.y, h)

  // Recompute a cheap normal via finite differences of the height field.
  const eps = float(0.5)
  const hL = heightAt(vec3(positionLocal.x.sub(eps), positionLocal.y, 0).xy)
  const hR = heightAt(vec3(positionLocal.x.add(eps), positionLocal.y, 0).xy)
  const hD = heightAt(vec3(positionLocal.x, positionLocal.y.sub(eps), 0).xy)
  const hU = heightAt(vec3(positionLocal.x, positionLocal.y.add(eps), 0).xy)
  // gradient -> normal in LOCAL space. The plane lies in local XY with height
  // along local +Z, so the up-axis of the surface is local +Z. three transforms
  // normalNode by the normal matrix (the mesh's -90deg X rotation), giving the
  // correct world normal.
  const n = vec3(hL.sub(hR), hD.sub(hU), eps.mul(2)).normalize()
  mat.normalNode = n

  // Slope = how flat (n.z close to 1 => flat). Height normalised 0..1.
  const hN = clamp(h.div(amp).mul(0.5).add(0.5), 0, 1)
  const slope = clamp(float(1).sub(n.z), 0, 1)

  const sand = color(PAL.sand)
  const grass = color(PAL.grass)
  const grassDark = color(PAL.grassDark)
  const rock = color(PAL.rock)
  const snow = color(PAL.snow)

  // Altitude bands
  let albedo = mix(sand, grass, smoothstep(0.18, 0.3, hN))
  albedo = mix(albedo, grassDark, smoothstep(0.3, 0.5, hN))
  albedo = mix(albedo, rock, smoothstep(0.55, 0.72, hN))
  albedo = mix(albedo, snow, smoothstep(0.82, 0.95, hN))
  // Slope blends toward rock on steep faces
  albedo = mix(albedo, rock, smoothstep(0.35, 0.7, slope))

  mat.colorNode = vec4(albedo, 1.0)
  return mat
}

/** Sky/gradient dome material (inside-out sphere, unlit). */
export function makeSkyMaterial() {
  const mat = new MeshBasicNodeMaterial()
  mat.side = DoubleSide
  const up = clamp(normalWorld.y.mul(-1).mul(0.5).add(0.5), 0, 1) // inverted normals on inside
  const horizon = color(PAL.horizon)
  const skyLow = color(PAL.sky)
  const skyHigh = color(PAL.skyHigh)
  let c = mix(horizon, skyLow, smoothstep(0.0, 0.25, up))
  c = mix(c, skyHigh, smoothstep(0.25, 0.85, up))
  mat.colorNode = vec4(c, 1.0)
  mat.fog = false
  return mat
}

/** Animated water plane: subtle TSL wave displacement + fresnel-ish tint. */
export function makeWaterMaterial() {
  const mat = new MeshStandardNodeMaterial()
  mat.transparent = true
  mat.metalness = 0.1
  mat.roughness = 0.25

  // timerLocal(scale) returns an elapsed-time node already multiplied by scale.
  const t = time(0.4)
  const p = positionLocal.xy.mul(0.12)
  const wave = mx_noise_float(vec3(p.x.add(t), p.y.sub(t), 0)).mul(0.25)
  mat.positionNode = vec3(positionLocal.x, positionLocal.y, wave)

  const deep = color(PAL.waterDeep)
  const shallow = color(PAL.water)
  const fres = clamp(float(1).sub(abs(dot(normalWorld, vec3(0, 1, 0)))), 0, 1)
  const c = mix(deep, shallow, fres.add(0.3))
  mat.colorNode = vec4(c, 0.72)
  return mat
}

/** Instanced "ant" material — flat-shaded, role-tinted via instanceColor. */
export function makeAntMaterial() {
  const mat = new MeshStandardNodeMaterial()
  mat.metalness = 0.0
  mat.roughness = 0.6
  // Read the per-instance color buffer (set via setColorAt) explicitly as a
  // vec3 attribute and use it as albedo. MeshStandardNodeMaterial in r0.169
  // does not auto-wire instanceColor the way the WebGL MeshStandardMaterial
  // does, so we bind it ourselves.
  mat.colorNode = vec4(attribute('instanceColor', 'vec3'), 1.0)
  return mat
}

export { uv }
