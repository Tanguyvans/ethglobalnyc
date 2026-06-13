/**
 * boids.ts — MOVEMENT ONLY. Reads positions/velocities/targets + the spatial
 * hash, applies classic flocking (separation / alignment / cohesion) plus a
 * seek toward each agent's target and soft world bounds, then integrates.
 *
 * No knowledge of roles' meaning, betting, or lifecycle — that's domain.ts.
 * Fully allocation-free: all temporaries are module-scoped scalars.
 */

import { sim, WORLD_HALF } from '../store/simStore'
import { groundY } from '../utils/noise'
import { Role } from '../data/schema'

const PERCEPTION = 8 // matches spatial-hash cell size
const PERCEPTION_SQ = PERCEPTION * PERCEPTION
const SEPARATION = 3.2
const SEPARATION_SQ = SEPARATION * SEPARATION

const BOUNDS = WORLD_HALF * 0.94

// steering weights
const W_SEP = 1.7
const W_ALI = 0.9
const W_COH = 0.7
const W_SEEK = 1.1

// per-role cruising speed multiplier (explorers roam faster)
const ROLE_SPEED: Record<Role, number> = {
  [Role.Worker]: 1.0,
  [Role.Explorer]: 1.45,
  [Role.Carrier]: 0.85,
  [Role.Builder]: 0.7,
  [Role.Messenger]: 1.25,
}

const BASE_SPEED = 9
const MAX_FORCE = 26

export function updateBoids(dt: number) {
  const { positions: P, velocities: V, targets: T, roles, count } = sim

  for (let i = 0; i < count; i++) {
    const i3 = i * 3
    const px = P[i3]
    const pz = P[i3 + 2]

    // neighbor accumulators
    let sepX = 0
    let sepZ = 0
    let aliX = 0
    let aliZ = 0
    let cohX = 0
    let cohZ = 0
    let aliCount = 0
    let cohCount = 0

    sim.hash.forEachNeighbor(px, pz, (j) => {
      if (j === i) return
      const j3 = j * 3
      const dx = px - P[j3]
      const dz = pz - P[j3 + 2]
      const d2 = dx * dx + dz * dz
      if (d2 > PERCEPTION_SQ || d2 === 0) return

      // alignment + cohesion within perception
      aliX += V[j3]
      aliZ += V[j3 + 2]
      aliCount++
      cohX += P[j3]
      cohZ += P[j3 + 2]
      cohCount++

      // separation only when very close, weighted by inverse distance
      if (d2 < SEPARATION_SQ) {
        const inv = 1 / Math.sqrt(d2)
        sepX += (dx * inv) / Math.sqrt(d2)
        sepZ += (dz * inv) / Math.sqrt(d2)
      }
    })

    // accumulate desired velocity components
    let ax = 0
    let az = 0

    ax += sepX * W_SEP
    az += sepZ * W_SEP

    if (aliCount > 0) {
      ax += (aliX / aliCount) * W_ALI * 0.1
      az += (aliZ / aliCount) * W_ALI * 0.1
    }
    if (cohCount > 0) {
      const cx = cohX / cohCount - px
      const cz = cohZ / cohCount - pz
      ax += cx * W_COH * 0.05
      az += cz * W_COH * 0.05
    }

    // seek target (set by domain)
    const tx = T[i3] - px
    const tz = T[i3 + 2] - pz
    const td = Math.hypot(tx, tz)
    if (td > 0.001) {
      ax += (tx / td) * W_SEEK * BASE_SPEED
      az += (tz / td) * W_SEEK * BASE_SPEED
    }

    // soft bounds — steer back toward center near the edge
    if (px > BOUNDS) ax -= (px - BOUNDS) * 1.5
    else if (px < -BOUNDS) ax -= (px + BOUNDS) * 1.5
    if (pz > BOUNDS) az -= (pz - BOUNDS) * 1.5
    else if (pz < -BOUNDS) az -= (pz + BOUNDS) * 1.5

    // clamp steering force
    const af = Math.hypot(ax, az)
    if (af > MAX_FORCE) {
      const s = MAX_FORCE / af
      ax *= s
      az *= s
    }

    // integrate velocity
    V[i3] += ax * dt
    V[i3 + 2] += az * dt

    // clamp to role max speed
    const maxSpeed = BASE_SPEED * ROLE_SPEED[roles[i] as Role]
    const speed = Math.hypot(V[i3], V[i3 + 2])
    if (speed > maxSpeed) {
      const s = maxSpeed / speed
      V[i3] *= s
      V[i3 + 2] *= s
    }

    // integrate position
    const nx = px + V[i3] * dt
    const nz = pz + V[i3 + 2] * dt
    P[i3] = nx
    P[i3 + 2] = nz
    // sit on the voxel surface with a small hover offset
    P[i3 + 1] = groundY(nx, nz) + 1.2
  }
}
