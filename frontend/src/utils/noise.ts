/**
 * Lightweight value-noise for procedural terrain height.
 * Deterministic given a seed; cheap fractal Brownian motion (fBm).
 * Used both on the CPU (sampling ground height for agents/camera) and to
 * pre-displace terrain geometry vertices.
 */

import { mulberry32 } from './math'

const PERM_SIZE = 256
const perm = new Uint8Array(PERM_SIZE * 2)
const grad = new Float32Array(PERM_SIZE)

let initialized = false

function init(seed = 1337) {
  const rand = mulberry32(seed)
  for (let i = 0; i < PERM_SIZE; i++) {
    perm[i] = i
    grad[i] = rand() * 2 - 1
  }
  // Shuffle
  for (let i = PERM_SIZE - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    const tmp = perm[i]
    perm[i] = perm[j]
    perm[j] = tmp
  }
  for (let i = 0; i < PERM_SIZE; i++) perm[PERM_SIZE + i] = perm[i]
  initialized = true
}

const fade = (t: number) => t * t * t * (t * (t * 6 - 15) + 10)
const lerpN = (a: number, b: number, t: number) => a + t * (b - a)

/** 2D value noise in [-1, 1]. */
export function noise2D(x: number, y: number): number {
  if (!initialized) init()
  const xi = Math.floor(x) & 255
  const yi = Math.floor(y) & 255
  const xf = x - Math.floor(x)
  const yf = y - Math.floor(y)
  const u = fade(xf)
  const v = fade(yf)

  const aa = grad[perm[perm[xi] + yi]]
  const ab = grad[perm[perm[xi] + yi + 1]]
  const ba = grad[perm[perm[xi + 1] + yi]]
  const bb = grad[perm[perm[xi + 1] + yi + 1]]

  const x1 = lerpN(aa, ba, u)
  const x2 = lerpN(ab, bb, u)
  return lerpN(x1, x2, v)
}

/** Fractal Brownian motion: layered noise for rolling hills. */
export function fbm(x: number, y: number, octaves = 4, lacunarity = 2, gain = 0.5): number {
  let amp = 0.5
  let freq = 1
  let sum = 0
  for (let i = 0; i < octaves; i++) {
    sum += amp * noise2D(x * freq, y * freq)
    freq *= lacunarity
    amp *= gain
  }
  return sum
}

/**
 * Canonical terrain height function. Shared by terrain geometry and any code
 * that needs to place objects on the ground. Keep params here in one place.
 */
export const TERRAIN = {
  scale: 0.01, // horizontal frequency
  amplitude: 18, // vertical scale of hills (dramatic, Minecraft-ish)
  octaves: 4,
}

/** Legacy voxel params — kept for the few callers that still spread by them. */
export const BLOCK = 4
export const VOXEL_HALF = 180

/** Water surface height. Anything below this is flooded (lakes / sea). */
export const WATER_LEVEL = -3.5

/**
 * Continuous terrain height (smooth noise). Two octave sets layered: broad
 * rolling hills plus a sharper ridge term so peaks read as rocky highlands and
 * basins pool into water. This is the single canonical surface function.
 */
export function terrainHeight(x: number, z: number): number {
  const base = fbm(x * TERRAIN.scale, z * TERRAIN.scale, TERRAIN.octaves) * TERRAIN.amplitude
  // ridged detail on the uplands for craggier peaks
  const ridge = (1 - Math.abs(noise2D(x * 0.018 + 11, z * 0.018 - 7))) * 6
  const lift = base > 4 ? (ridge - 3) * Math.min((base - 4) / 10, 1) : 0
  return base + lift
}

/**
 * Canonical ground surface Y at (x,z) — now SMOOTH (no block quantization).
 * Ants (boids snap here every frame), the colony, resources and the
 * first-person camera all ride this, so the world stays in sync with the
 * displaced terrain mesh which is built from the same function.
 */
export function groundY(x: number, z: number): number {
  return terrainHeight(x, z)
}

/**
 * Surface steepness at (x,z) in [0,1] via central differences. Used to blend
 * rock onto cliffs and to keep vegetation off steep faces.
 */
export function terrainSlope(x: number, z: number, eps = 2): number {
  const dx = (terrainHeight(x + eps, z) - terrainHeight(x - eps, z)) / (2 * eps)
  const dz = (terrainHeight(x, z + eps) - terrainHeight(x, z - eps)) / (2 * eps)
  return Math.min(1, Math.hypot(dx, dz))
}
