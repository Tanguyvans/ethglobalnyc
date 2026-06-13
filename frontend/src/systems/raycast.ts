/**
 * raycast.ts — efficient ant picking WITHOUT raycasting every instance. The
 * caller provides a world-space ground point (from a single terrain raycast);
 * we query the spatial hash around it and return the nearest ant within radius.
 * O(neighbors), not O(agents).
 */

import { sim } from '../store/simStore'

const PICK_RADIUS = 6
const PICK_RADIUS_SQ = PICK_RADIUS * PICK_RADIUS

/** Returns the nearest ant index near (x,z), or null if none in radius. */
export function pickAnt(x: number, z: number): number | null {
  let best = -1
  let bestD = PICK_RADIUS_SQ
  sim.hash.forEachNeighbor(x, z, (i) => {
    const i3 = i * 3
    const dx = sim.positions[i3] - x
    const dz = sim.positions[i3 + 2] - z
    const d = dx * dx + dz * dz
    if (d < bestD) {
      bestD = d
      best = i
    }
  })
  return best >= 0 ? best : null
}
