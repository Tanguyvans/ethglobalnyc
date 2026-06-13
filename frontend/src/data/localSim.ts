/**
 * localSim — the always-on SimSource. The core boids/domain simulation is
 * stepped elsewhere (useFrameSim); localSim's job is to synthesize plausible
 * *domain events* (debate pulses, stake flows) so the world reads as alive and
 * "thinking" even with no harness replay loaded.
 */

import type { SimSource, EventSink } from './adapter'
import { sim, type SideCode } from '../store/simStore'
import { Role, AntState } from '../data/schema'
import { mulberry32 } from '../utils/math'

const rng = mulberry32(0x5eed)

const COMM_RATE = 6 // pulses/sec (scaled by population)
const STAKE_RATE = 4 // flows/sec

export class LocalSim implements SimSource {
  readonly id = 'local' as const
  private sink: EventSink | null = null
  private commAcc = 0
  private stakeAcc = 0

  start(sink: EventSink) {
    this.sink = sink
  }

  update(dt: number) {
    if (!this.sink || sim.count === 0) return
    const scale = sim.count / 500

    this.commAcc += COMM_RATE * scale * dt
    while (this.commAcc >= 1) {
      this.commAcc -= 1
      this.emitComm()
    }

    this.stakeAcc += STAKE_RATE * scale * dt
    while (this.stakeAcc >= 1) {
      this.stakeAcc -= 1
      this.emitStake()
    }
  }

  private emitComm() {
    const from = (rng() * sim.count) | 0
    // messengers and debating ants talk to the colony; others to a neighbor
    const role = sim.roles[from] as Role
    const toColony = role === Role.Messenger || sim.states[from] === AntState.Debating || rng() < 0.5
    const to = toColony ? -1 : (rng() * sim.count) | 0
    const hue = sim.homeProb[from] // hot = home-leaning
    this.sink!.comm(from, to, hue)
  }

  private emitStake() {
    const a = (rng() * sim.count) | 0
    const lean = sim.homeProb[a]
    const side: SideCode = lean > 0.55 ? 1 : lean < 0.45 ? -1 : 0
    if (side === 0) return
    const amount = 0.2 + rng() * 0.8
    const win = rng() < 0.5 + (sim.accuracy[a] - 0.5)
    this.sink!.stake(a, side, amount, win)
  }

  stop() {
    this.sink = null
  }
}
