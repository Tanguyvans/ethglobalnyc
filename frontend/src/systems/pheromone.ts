/**
 * pheromone.ts — stigmergy. Each colony keeps two evaporating, diffusing scalar
 * grids over the world:
 *   • TO_FOOD — laid by ants HAULING food home; searching ants climb it to find
 *     the resource (recruitment + shortest-path emergence).
 *   • TO_HOME — laid by ants LEAVING the nest; carriers climb it back home.
 * This is the classic dual-pheromone ant model — trails self-reinforce when used
 * and fade when not, so the network tracks the live food supply.
 *
 * Allocation-free per frame: fixed grids + a shared scratch buffer.
 */

import { WORLD_HALF } from '../store/simStore'

export const CELL = 6
export const DIM = Math.ceil((WORLD_HALF * 2) / CELL) + 1
const CELLS = DIM * DIM

export const TO_FOOD = 0
export const TO_HOME = 1
const MAX_PHER = 8

class PheromoneField {
  /** grids[colonyId] = [toFood, toHome] */
  readonly grids: Float32Array[][] = []
  private readonly scratch = new Float32Array(CELLS)
  nColonies = 0

  reset(n: number) {
    this.nColonies = n
    this.grids.length = 0
    for (let c = 0; c < n; c++) {
      this.grids.push([new Float32Array(CELLS), new Float32Array(CELLS)])
    }
  }

  private idx(x: number, z: number): number {
    let cx = ((x + WORLD_HALF) / CELL) | 0
    let cz = ((z + WORLD_HALF) / CELL) | 0
    if (cx < 0) cx = 0
    else if (cx >= DIM) cx = DIM - 1
    if (cz < 0) cz = 0
    else if (cz >= DIM) cz = DIM - 1
    return cz * DIM + cx
  }

  /** world center of a grid cell (for the trail renderer). */
  cellX(i: number): number {
    return ((i % DIM) + 0.5) * CELL - WORLD_HALF
  }
  cellZ(i: number): number {
    return ((i / DIM) | 0) * CELL + 0.5 * CELL - WORLD_HALF
  }

  deposit(cid: number, ch: number, x: number, z: number, amt: number) {
    const g = this.grids[cid]?.[ch]
    if (!g) return
    const i = this.idx(x, z)
    const v = g[i] + amt
    g[i] = v > MAX_PHER ? MAX_PHER : v
  }

  sample(cid: number, ch: number, x: number, z: number): number {
    const g = this.grids[cid]?.[ch]
    if (!g) return 0
    return g[this.idx(x, z)]
  }

  /**
   * Steer toward higher concentration of channel `ch` ahead of heading (hx,hz).
   * Writes a unit direction into out[0],out[1]; returns false if the trail ahead
   * is too faint to follow (caller should wander).
   */
  gradient(
    cid: number,
    ch: number,
    x: number,
    z: number,
    hx: number,
    hz: number,
    out: Float32Array,
  ): boolean {
    const LOOK = CELL * 1.8
    let base = Math.atan2(hz, hx)
    if (!isFinite(base) || (hx === 0 && hz === 0)) base = 0
    let bestC = 0
    let bestA = base
    for (let k = -1; k <= 1; k++) {
      const ang = base + k * 0.7
      const c = this.sample(cid, ch, x + Math.cos(ang) * LOOK, z + Math.sin(ang) * LOOK)
      if (c > bestC) {
        bestC = c
        bestA = ang
      }
    }
    if (bestC < 0.04) return false
    out[0] = Math.cos(bestA)
    out[1] = Math.sin(bestA)
    return true
  }

  /** Evaporate + diffuse every grid once per tick. */
  update(dt: number) {
    const evap = Math.pow(0.82, dt) // ~18%/s decay
    const diffuse = Math.min(0.18, dt * 1.5)
    const s = this.scratch
    for (let c = 0; c < this.grids.length; c++) {
      for (let ch = 0; ch < 2; ch++) {
        const g = this.grids[c][ch]
        s.set(g)
        for (let zi = 0; zi < DIM; zi++) {
          const row = zi * DIM
          for (let xi = 0; xi < DIM; xi++) {
            const i = row + xi
            const cur = s[i]
            // 4-neighbour average (clamped edges reuse self)
            const l = xi > 0 ? s[i - 1] : cur
            const r = xi < DIM - 1 ? s[i + 1] : cur
            const u = zi > 0 ? s[i - DIM] : cur
            const d = zi < DIM - 1 ? s[i + DIM] : cur
            const avg = (l + r + u + d) * 0.25
            g[i] = (cur + (avg - cur) * diffuse) * evap
          }
        }
      }
    }
  }
}

/** Module singleton. */
export const pher = new PheromoneField()
