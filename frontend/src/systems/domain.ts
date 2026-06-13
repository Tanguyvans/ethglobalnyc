/**
 * domain.ts — the MEANING behind the motion. Owns role behavior, the resource
 * economy (seek → carry → deposit), accuracy/bankroll drift, the colony health
 * aggregate, and per-agent state transitions. It only ever writes `targets`,
 * `states`, and domain scalar arrays; boids.ts turns targets into movement.
 *
 * Runs every tick but most work is gated by cheap stochastic rates so it stays
 * well under budget at 2000 agents.
 */

import { sim } from '../store/simStore'
import { Role, AntState } from '../data/schema'
import { mulberry32, clamp, lenXZ } from '../utils/math'

const rng = mulberry32(0xc0ffee)

const RESOURCE_REACH = 6
const RESOURCE_REACH_SQ = RESOURCE_REACH * RESOURCE_REACH
const COLONY_REACH = 16
const COLONY_REACH_SQ = COLONY_REACH * COLONY_REACH
const BITE = 0.012 // energy removed per pickup
const RESPAWN_RATE = 0.015 // energy regained per second

function setTarget(i: number, x: number, z: number) {
  const i3 = i * 3
  sim.targets[i3] = x
  sim.targets[i3 + 2] = z
}

function nearestResource(px: number, pz: number): number {
  let best = -1
  let bestD = Infinity
  const R = sim.resources
  for (let r = 0; r < R.length; r++) {
    if (R[r].energy < 0.05) continue
    const dx = R[r].x - px
    const dz = R[r].z - pz
    const d = dx * dx + dz * dz
    if (d < bestD) {
      bestD = d
      best = r
    }
  }
  return best
}

export function updateDomain(dt: number) {
  const { positions: P, states, roles, colonies, resources, count } = sim
  if (colonies.length === 0) return
  const colony = colonies[0]

  // Resource regrowth + reset per-tick worker counts.
  for (let r = 0; r < resources.length; r++) {
    resources[r].energy = clamp(resources[r].energy + RESPAWN_RATE * dt, 0, 1)
    resources[r].activeWorkers = 0
  }

  let bankrollSum = 0
  let accSum = 0
  let verifiedSum = 0

  for (let i = 0; i < count; i++) {
    const i3 = i * 3
    const px = P[i3]
    const pz = P[i3 + 2]
    const role = roles[i] as Role
    let state = states[i] as AntState

    // decay transient highlight (debate glow)
    if (sim.highlight[i] > 0) sim.highlight[i] = Math.max(0, sim.highlight[i] - dt * 1.6)

    switch (state) {
      case AntState.Wander: {
        if (role === Role.Messenger && rng() < 0.4 * dt) {
          state = AntState.Debating
          setTarget(i, colony.x, colony.z)
        } else if (role === Role.Builder) {
          // builders linger near the colony
          if (lenXZ(px - colony.x, pz - colony.z) > COLONY_REACH * 1.5) {
            setTarget(i, colony.x, colony.z)
          } else if (rng() < 0.5 * dt) {
            const a = rng() * Math.PI * 2
            setTarget(i, colony.x + Math.cos(a) * 12, colony.z + Math.sin(a) * 12)
          }
        } else if (role === Role.Explorer) {
          // explorers roam to far points
          if (rng() < 0.4 * dt) {
            const a = rng() * Math.PI * 2
            const r = 60 + rng() * 130
            setTarget(i, Math.cos(a) * r, Math.sin(a) * r)
          }
        } else {
          // workers / carriers seek resources
          if (rng() < 1.5 * dt) {
            const r = nearestResource(px, pz)
            if (r >= 0) {
              state = AntState.SeekResource
              setTarget(i, resources[r].x, resources[r].z)
            }
          }
        }
        break
      }

      case AntState.SeekResource: {
        const r = nearestResource(px, pz)
        if (r < 0) {
          state = AntState.Wander
          break
        }
        const res = resources[r]
        res.activeWorkers++
        setTarget(i, res.x, res.z)
        const dx = res.x - px
        const dz = res.z - pz
        if (dx * dx + dz * dz < RESOURCE_REACH_SQ) {
          res.energy = clamp(res.energy - BITE, 0, 1)
          sim.stake[i] = 0.3 + rng() * 0.7
          state = AntState.Carrying
          setTarget(i, colony.x, colony.z)
        }
        break
      }

      case AntState.Carrying: {
        setTarget(i, colony.x, colony.z)
        const dx = colony.x - px
        const dz = colony.z - pz
        if (dx * dx + dz * dz < COLONY_REACH_SQ) {
          // deposit: small bankroll + accuracy nudge
          sim.bankrolls[i] = clamp(sim.bankrolls[i] + sim.stake[i] * 2, 0, 1000)
          sim.accuracy[i] = clamp(sim.accuracy[i] + (rng() - 0.45) * 0.01, 0.05, 0.95)
          sim.stake[i] = 0
          state = AntState.Wander
        }
        break
      }

      case AntState.Debating: {
        setTarget(i, colony.x, colony.z)
        sim.highlight[i] = 1
        if (rng() < 1.2 * dt) state = AntState.Wander
        break
      }

      case AntState.ReturnHome: {
        setTarget(i, colony.x, colony.z)
        const dx = colony.x - px
        const dz = colony.z - pz
        if (dx * dx + dz * dz < COLONY_REACH_SQ) state = AntState.Wander
        break
      }
    }

    // gentle homeProb drift toward market w/ noise (visual liveliness)
    sim.homeProb[i] = clamp(sim.homeProb[i] + (rng() - 0.5) * 0.04 * dt, 0.05, 0.95)

    states[i] = state
    bankrollSum += sim.bankrolls[i]
    accSum += sim.accuracy[i]
    verifiedSum += sim.verified[i]
  }

  // Update colony aggregate (cheap; once per tick).
  if (count > 0) {
    colony.population = count
    colony.bankroll = bankrollSum / count
    colony.accuracy = accSum / count
    colony.verifiedRatio = verifiedSum / count
    // health blends normalized wealth and accuracy
    const wealthNorm = clamp((colony.bankroll - 80) / 60, 0, 1)
    colony.health = clamp(wealthNorm * 0.5 + colony.accuracy * 0.5, 0, 1)
    colony.growthRate = clamp(colony.health, 0, 1)
  }
}
