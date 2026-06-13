/**
 * simulation.ts — the single orchestrator. Called once per frame from one
 * useFrame. Order per the plan: rebuild spatial hash → domain → boids. The
 * caller (useFrameSim) is then responsible for pushing positions into the
 * InstancedMesh; the sim never touches three.js objects.
 */

import { sim } from '../store/simStore'
import { updateDomain } from './domain'
import { updateBoids } from './boids'
import { pher } from './pheromone'

const MAX_DT = 1 / 30 // clamp to avoid spiral-of-death on tab refocus

export function stepSimulation(rawDt: number) {
  const dt = rawDt > MAX_DT ? MAX_DT : rawDt
  sim.time += dt

  // 1. spatial hash for this frame's positions
  sim.hash.rebuild(sim.positions, sim.count)
  // 2. evaporate + diffuse last frame's pheromone deposits
  pher.update(dt)
  // 3. domain decisions (forage loop, brood/growth, castes, aggregates)
  updateDomain(dt)
  // 4. movement (follows + lays pheromone; territory + patrol)
  updateBoids(dt)
}
