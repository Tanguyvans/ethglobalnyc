/**
 * flowBuffer — fixed-size buffer of stake-flow particles (USDC forecasts).
 * Each particle travels along a quadratic curve between an agent and the
 * colony. `side` tints it (home/away), `amount` scales its size, and `win`
 * decides whether it accelerates into the colony or fades out mid-path.
 * Read by the StakeFlows renderer; allocation-free.
 */

import type { SideCode } from '../store/simStore'

export const MAX_FLOWS = 384

class FlowBuffer {
  // endpoints (a = agent, b = colony) and a lifted control point for the arc
  readonly ax = new Float32Array(MAX_FLOWS)
  readonly ay = new Float32Array(MAX_FLOWS)
  readonly az = new Float32Array(MAX_FLOWS)
  readonly bx = new Float32Array(MAX_FLOWS)
  readonly by = new Float32Array(MAX_FLOWS)
  readonly bz = new Float32Array(MAX_FLOWS)
  readonly cx = new Float32Array(MAX_FLOWS)
  readonly cy = new Float32Array(MAX_FLOWS)
  readonly cz = new Float32Array(MAX_FLOWS)
  readonly t = new Float32Array(MAX_FLOWS)
  readonly life = new Float32Array(MAX_FLOWS)
  readonly size = new Float32Array(MAX_FLOWS)
  readonly side = new Int8Array(MAX_FLOWS)
  readonly win = new Uint8Array(MAX_FLOWS)
  readonly active = new Uint8Array(MAX_FLOWS)

  private head = 0

  spawn(
    ax: number,
    ay: number,
    az: number,
    bx: number,
    by: number,
    bz: number,
    side: SideCode,
    amount: number,
    win: boolean,
  ) {
    const i = this.head
    this.head = (this.head + 1) % MAX_FLOWS
    this.ax[i] = ax
    this.ay[i] = ay
    this.az[i] = az
    this.bx[i] = bx
    this.by[i] = by
    this.bz[i] = bz
    // control point: midpoint lifted up for a graceful arc
    this.cx[i] = (ax + bx) * 0.5
    this.cy[i] = Math.max(ay, by) + 6 + amount * 4
    this.cz[i] = (az + bz) * 0.5
    this.t[i] = 0
    this.life[i] = 1.6
    this.size[i] = 0.4 + amount * 1.1
    this.side[i] = side
    this.win[i] = win ? 1 : 0
    this.active[i] = 1
  }

  update(dt: number) {
    for (let i = 0; i < MAX_FLOWS; i++) {
      if (!this.active[i]) continue
      // winning flows speed up toward the colony; losers run normal then fade
      const speed = this.win[i] ? 0.75 + this.t[i] * 0.4 : 0.7
      this.t[i] += dt * speed
      if (this.t[i] >= this.life[i]) this.active[i] = 0
    }
  }
}

export const flowBuffer = new FlowBuffer()
