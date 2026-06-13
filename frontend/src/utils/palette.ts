/** Central color system — vivid, blocky, sunlit (Minecraft-style world). */

import { Color } from 'three'
import { Role, AntState } from '../data/schema'
import { WATER_LEVEL } from './noise'

export const PALETTE = {
  // sky + atmosphere
  sky: '#9fd0ff',
  skyHigh: '#5aa9f0',
  horizon: '#dcefff',
  sun: '#fff1cf',

  // biome bands (by altitude) — naturalistic, slightly desaturated
  water: '#2f6fb0',
  waterDeep: '#1c4a7d',
  sand: '#d8c79c',
  grass: '#4f8f3c',
  grassDark: '#3a6e2b',
  dirt: '#7d5536',
  rock: '#7c756b',
  rockDark: '#5d564e',
  snow: '#eef3f8',

  // agents
  worker: '#34e07a',
  explorer: '#3ab4ff',
  carrier: '#ffa53a',
  builder: '#b07cff',
  messenger: '#ff5e9c',
  resource: '#ffb02e',
  verified: '#ffd23f',
} as const

/** Role -> base color, indexed by Role enum value. */
export const ROLE_COLORS: Record<Role, Color> = {
  [Role.Worker]: new Color(PALETTE.worker),
  [Role.Explorer]: new Color(PALETTE.explorer),
  [Role.Carrier]: new Color(PALETTE.carrier),
  [Role.Builder]: new Color(PALETTE.builder),
  [Role.Messenger]: new Color(PALETTE.messenger),
}

export const VERIFIED_COLOR = new Color(PALETTE.verified)

/** Hex string per role (for DOM swatches / legend). */
export const ROLE_HEX: Record<Role, string> = {
  [Role.Worker]: PALETTE.worker,
  [Role.Explorer]: PALETTE.explorer,
  [Role.Carrier]: PALETTE.carrier,
  [Role.Builder]: PALETTE.builder,
  [Role.Messenger]: PALETTE.messenger,
}

/** Human-readable role labels for UI. */
export const ROLE_LABELS: Record<Role, string> = {
  [Role.Worker]: 'Worker',
  [Role.Explorer]: 'Explorer',
  [Role.Carrier]: 'Carrier',
  [Role.Builder]: 'Builder',
  [Role.Messenger]: 'Messenger',
}

/** Human-readable state labels for UI. */
export const STATE_LABELS: Record<AntState, string> = {
  [AntState.Wander]: 'Wandering',
  [AntState.SeekResource]: 'Seeking resource',
  [AntState.Carrying]: 'Carrying stake',
  [AntState.ReturnHome]: 'Returning',
  [AntState.Debating]: 'Debating',
}

// pre-built biome colors (avoid per-vertex allocation)
const _sand = new Color(PALETTE.sand)
const _grass = new Color(PALETTE.grass)
const _grassDark = new Color(PALETTE.grassDark)
const _rock = new Color(PALETTE.rock)
const _rockDark = new Color(PALETTE.rockDark)
const _snow = new Color(PALETTE.snow)

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/**
 * Naturalistic surface color from altitude + slope, smoothly blended (no hard
 * bands). Beaches near the water line, grass in the lowlands darkening with
 * height, rock pushed onto steep faces, snow on the high peaks.
 */
export function biomeColor(y: number, slope: number, out: Color): Color {
  const shore = WATER_LEVEL + 2.5
  // altitude blend: sand -> grass -> dark grass -> rock -> snow
  out.copy(_sand)
  out.lerp(_grass, smoothstep(shore, shore + 4, y))
  out.lerp(_grassDark, smoothstep(shore + 6, 16, y))
  out.lerp(_rock, smoothstep(16, 26, y))
  out.lerp(_snow, smoothstep(30, 40, y))
  // steep faces become rock regardless of altitude (cliffs)
  const rocky = smoothstep(0.45, 0.85, slope)
  if (rocky > 0) out.lerp(y > 28 ? _rockDark : _rock, rocky * 0.85)
  return out
}
