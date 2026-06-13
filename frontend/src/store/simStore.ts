/**
 * simStore — the non-React simulation state. ALL per-frame agent data lives
 * here in flat typed arrays (Structure-of-Arrays) so the render loop never
 * touches React state. Components read these buffers directly inside useFrame.
 *
 * Capacity is fixed at construction (MAX_AGENTS); `count` is the active number.
 * Nothing in here allocates per frame.
 */

import { Role, AntState } from '../data/schema'
import { groundY } from '../utils/noise'
import { SpatialHash } from '../systems/spatialHash'

export const MAX_AGENTS = 2048
export const MAX_COLONIES = 4
export const MAX_RESOURCES = 24
export const WORLD_HALF = 220 // world spans [-WORLD_HALF, WORLD_HALF] on X/Z
export const HASH_CELL = 8 // ≈ boids perception radius

export interface ColonyData {
  x: number
  z: number
  /** aggregate, updated by domain/replay (0..1 unless noted) */
  population: number
  bankroll: number
  accuracy: number
  growthRate: number
  verifiedRatio: number
  /** 0..1 derived health (wealth+accuracy) for visual intensity */
  health: number
}

export interface ResourceData {
  x: number
  z: number
  y: number
  energy: number // 0..1
  activeWorkers: number
}

/** Side stored as int8: 1 home, -1 away, 0 pass/none. */
export type SideCode = -1 | 0 | 1

class SimStore {
  // --- agent SoA buffers ---
  readonly positions = new Float32Array(MAX_AGENTS * 3)
  readonly velocities = new Float32Array(MAX_AGENTS * 3)
  readonly targets = new Float32Array(MAX_AGENTS * 3)
  readonly roles = new Uint8Array(MAX_AGENTS)
  readonly states = new Uint8Array(MAX_AGENTS)
  readonly bankrolls = new Float32Array(MAX_AGENTS)
  readonly accuracy = new Float32Array(MAX_AGENTS)
  readonly homeProb = new Float32Array(MAX_AGENTS)
  readonly stake = new Float32Array(MAX_AGENTS)
  readonly side = new Int8Array(MAX_AGENTS)
  readonly verified = new Uint8Array(MAX_AGENTS)
  readonly colonyId = new Uint8Array(MAX_AGENTS)
  readonly phase = new Float32Array(MAX_AGENTS) // animation offset
  readonly highlight = new Float32Array(MAX_AGENTS) // 0..1 transient glow (e.g. debating)

  /** index -> harness agent_id (filled by replay roster; '' otherwise). */
  readonly agentIds: string[] = new Array(MAX_AGENTS).fill('')
  /** index -> display name / genome hash (UI only; from roster export). */
  readonly names: string[] = new Array(MAX_AGENTS).fill('')
  readonly genomeHashes: string[] = new Array(MAX_AGENTS).fill('')
  readonly generations = new Int16Array(MAX_AGENTS)
  /** quick reverse lookup for replay binding. */
  readonly idToIndex = new Map<string, number>()

  count = 0

  readonly colonies: ColonyData[] = []
  readonly resources: ResourceData[] = []

  /** spatial hash, rebuilt each tick by the orchestrator before boids. */
  readonly hash = new SpatialHash(HASH_CELL)

  /** simulation clock (seconds), advanced by the orchestrator. */
  time = 0

  /**
   * Initialize a population around a single colony at origin, plus resource
   * nodes scattered on the terrain. Deterministic given `rand`.
   */
  init(count: number, rand: () => number) {
    this.count = Math.min(count, MAX_AGENTS)
    this.colonies.length = 0
    this.resources.length = 0
    this.idToIndex.clear()
    this.time = 0

    // Single colony at origin for the vertical slice.
    const cx = 0
    const cz = 0
    this.colonies.push({
      x: cx,
      z: cz,
      population: this.count,
      bankroll: 100,
      accuracy: 0.5,
      growthRate: 0.5,
      verifiedRatio: 0.18,
      health: 0.6,
    })

    // Resource nodes in a ring around the colony.
    const RES = 10
    for (let i = 0; i < RES; i++) {
      const a = (i / RES) * Math.PI * 2 + rand() * 0.4
      const r = 55 + rand() * 95
      const x = Math.cos(a) * r
      const z = Math.sin(a) * r
      this.resources.push({
        x,
        z,
        y: groundY(x, z),
        energy: 0.5 + rand() * 0.5,
        activeWorkers: 0,
      })
    }

    for (let i = 0; i < this.count; i++) {
      const i3 = i * 3
      const a = rand() * Math.PI * 2
      const r = rand() * 22
      const x = cx + Math.cos(a) * r
      const z = cz + Math.sin(a) * r
      this.positions[i3] = x
      this.positions[i3 + 1] = groundY(x, z) + 1.2
      this.positions[i3 + 2] = z

      const sp = 0.4 + rand() * 0.4
      const va = rand() * Math.PI * 2
      this.velocities[i3] = Math.cos(va) * sp
      this.velocities[i3 + 1] = 0
      this.velocities[i3 + 2] = Math.sin(va) * sp

      this.targets[i3] = x
      this.targets[i3 + 1] = 0
      this.targets[i3 + 2] = z

      // Role distribution: mostly workers, some explorers/carriers, few builders/messengers.
      const roll = rand()
      this.roles[i] =
        roll < 0.5
          ? Role.Worker
          : roll < 0.72
            ? Role.Explorer
            : roll < 0.9
              ? Role.Carrier
              : roll < 0.97
                ? Role.Builder
                : Role.Messenger

      this.states[i] = AntState.Wander
      this.bankrolls[i] = 92 + rand() * 16
      this.accuracy[i] = 0.35 + rand() * 0.3
      this.homeProb[i] = 0.45 + rand() * 0.1
      this.stake[i] = 0
      this.side[i] = 0
      this.verified[i] = rand() < 0.18 ? 1 : 0
      this.colonyId[i] = 0
      this.phase[i] = rand() * Math.PI * 2
      this.highlight[i] = 0
      this.agentIds[i] = ''
      this.names[i] = `ant-${i.toString().padStart(4, '0')}`
      this.genomeHashes[i] = ''
      this.generations[i] = 0
    }
  }
}

/** Module singleton. */
export const sim = new SimStore()
