/**
 * Uniform-grid spatial hash over the XZ plane. Rebuilt each tick from the
 * agent position buffer. Backs boids neighbor lookup, raycast narrowing, and
 * proximity queries — the O(n) backbone for 500–2000 agents.
 *
 * Allocation-free in steady state: bucket arrays are reused across rebuilds.
 */

import { WORLD_HALF } from '../store/simStore'

export class SpatialHash {
  readonly cellSize: number
  private readonly cols: number
  private readonly buckets: number[][]

  constructor(cellSize: number) {
    this.cellSize = cellSize
    // grid covers [-WORLD_HALF, WORLD_HALF]
    this.cols = Math.ceil((WORLD_HALF * 2) / cellSize) + 1
    this.buckets = new Array(this.cols * this.cols)
    for (let i = 0; i < this.buckets.length; i++) this.buckets[i] = []
  }

  private cellIndex(x: number, z: number): number {
    let cx = Math.floor((x + WORLD_HALF) / this.cellSize)
    let cz = Math.floor((z + WORLD_HALF) / this.cellSize)
    if (cx < 0) cx = 0
    else if (cx >= this.cols) cx = this.cols - 1
    if (cz < 0) cz = 0
    else if (cz >= this.cols) cz = this.cols - 1
    return cz * this.cols + cx
  }

  /** Clear and refill from the position buffer (length = count*3, XYZ). */
  rebuild(positions: Float32Array, count: number) {
    const b = this.buckets
    for (let i = 0; i < b.length; i++) b[i].length = 0
    for (let i = 0; i < count; i++) {
      const i3 = i * 3
      b[this.cellIndex(positions[i3], positions[i3 + 2])].push(i)
    }
  }

  /**
   * Visit every agent index in the 3x3 cell block around (x,z) by calling
   * `fn(index)`. No array allocation; the caller filters by exact radius.
   */
  forEachNeighbor(x: number, z: number, fn: (index: number) => void) {
    const cx = Math.floor((x + WORLD_HALF) / this.cellSize)
    const cz = Math.floor((z + WORLD_HALF) / this.cellSize)
    for (let dz = -1; dz <= 1; dz++) {
      const rz = cz + dz
      if (rz < 0 || rz >= this.cols) continue
      for (let dx = -1; dx <= 1; dx++) {
        const rx = cx + dx
        if (rx < 0 || rx >= this.cols) continue
        const bucket = this.buckets[rz * this.cols + rx]
        for (let k = 0; k < bucket.length; k++) fn(bucket[k])
      }
    }
  }
}
