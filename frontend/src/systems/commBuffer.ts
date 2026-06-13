/**
 * commBuffer — fixed-size ring buffer of communication pulses (debate claims).
 * A pulse travels from a source point to a destination point over `life`
 * seconds. The renderer (CommLinks) reads these slots each frame and positions
 * instanced pulse quads along the path; nothing is allocated per event.
 */

export const MAX_PULSES = 256

class CommBuffer {
  // packed per-slot data
  readonly ax = new Float32Array(MAX_PULSES)
  readonly ay = new Float32Array(MAX_PULSES)
  readonly az = new Float32Array(MAX_PULSES)
  readonly bx = new Float32Array(MAX_PULSES)
  readonly by = new Float32Array(MAX_PULSES)
  readonly bz = new Float32Array(MAX_PULSES)
  readonly t = new Float32Array(MAX_PULSES) // elapsed
  readonly life = new Float32Array(MAX_PULSES)
  readonly hue = new Float32Array(MAX_PULSES) // 0..1
  readonly active = new Uint8Array(MAX_PULSES)

  private head = 0

  spawn(
    ax: number,
    ay: number,
    az: number,
    bx: number,
    by: number,
    bz: number,
    hue: number,
    life = 1.1,
  ) {
    const i = this.head
    this.head = (this.head + 1) % MAX_PULSES
    this.ax[i] = ax
    this.ay[i] = ay
    this.az[i] = az
    this.bx[i] = bx
    this.by[i] = by
    this.bz[i] = bz
    this.t[i] = 0
    this.life[i] = life
    this.hue[i] = hue
    this.active[i] = 1
  }

  update(dt: number) {
    for (let i = 0; i < MAX_PULSES; i++) {
      if (!this.active[i]) continue
      this.t[i] += dt
      if (this.t[i] >= this.life[i]) this.active[i] = 0
    }
  }
}

export const commBuffer = new CommBuffer()
