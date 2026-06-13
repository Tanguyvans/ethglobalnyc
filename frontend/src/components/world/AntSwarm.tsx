/**
 * AntSwarm — every agent from ONE InstancedMesh with per-instance color. The
 * body is a smooth, realistic ant (merged spheres: gaster + thorax + head, plus
 * tapered-cylinder legs + antennae) pointing +Z, oriented by velocity each
 * frame. Matrices + colors are written straight from the simStore typed arrays
 * — zero per-frame allocation.
 *
 * Not raycast directly (picking goes through ground + spatial hash).
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import {
  InstancedMesh,
  BufferGeometry,
  SphereGeometry,
  CylinderGeometry,
  Matrix4,
  Quaternion,
  Vector3,
  Euler,
  Color,
  DynamicDrawUsage,
} from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { sim, MAX_AGENTS } from '../../store/simStore'
import { AntTask } from '../../data/schema'
import { COLONY_COLORS, VERIFIED_COLOR } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'

const _m = new Matrix4()
const _q = new Quaternion()
const _e = new Euler()
const _p = new Vector3()
const _s = new Vector3()
const _c = new Color()
const SELECT = new Color('#ffffff')
const BODY = new Color('#21150e')
const AMBER = new Color('#9a5f2e')
const GOLD = new Color('#d8a94c') // queens
const SOLDIER = new Color('#7c2f23') // soldiers
const FOOD_GLOW = new Color('#d7c27a') // brighten while hauling food

const BASE_SCALE = 1.15

/** Build a smooth, realistic ant facing +Z, centered near origin, ~1.7 long. */
function buildAntGeometry() {
  const parts: BufferGeometry[] = []

  // body segments — scaled spheres (ellipsoids)
  const seg = (r: number, sx: number, sy: number, sz: number, y: number, z: number) => {
    const g = new SphereGeometry(r, 10, 8)
    g.scale(sx, sy, sz)
    g.translate(0, y, z)
    return g
  }
  parts.push(seg(0.42, 0.85, 0.8, 1.2, 0.0, -0.62)) // gaster (abdomen, rear)
  parts.push(seg(0.16, 1, 1, 1, 0.02, -0.16)) // petiole (waist)
  parts.push(seg(0.3, 0.95, 0.9, 1.05, 0.06, 0.14)) // thorax
  parts.push(seg(0.32, 1, 0.92, 0.92, 0.14, 0.66)) // head (front)

  // limbs — tapered cylinders, mirrored to both sides
  const limb = (
    len: number,
    rad: number,
    rotZ: number,
    rotY: number,
    x: number,
    y: number,
    z: number,
    side: number,
  ) => {
    const g = new CylinderGeometry(rad * 0.6, rad, len, 5)
    g.translate(0, len / 2, 0) // base at origin, extends +Y
    g.rotateZ(rotZ)
    g.rotateY(rotY)
    if (side < 0) g.scale(-1, 1, 1)
    g.translate(x * side, y, z)
    return g
  }
  // 3 legs per side, fanning front→back, angled out and down
  const legZ = [0.28, 0.04, -0.22]
  const legFan = [-0.5, 0.0, 0.55]
  for (let s = -1; s <= 1; s += 2) {
    for (let l = 0; l < 3; l++) {
      parts.push(limb(0.75, 0.05, -1.95, legFan[l], 0.16, 0.05, legZ[l], s))
    }
    // antenna from the head, forward + up + out
    parts.push(limb(0.5, 0.035, -0.55, -0.7, 0.12, 0.26, 0.78, s))
  }

  const merged = mergeGeometries(parts, false)!
  parts.forEach((p) => p.dispose())
  return merged
}

export default function AntSwarm() {
  const ref = useRef<InstancedMesh>(null)
  const agentCount = useWorldStore((s) => s.agentCount)

  const geometry = useMemo(buildAntGeometry, [])

  useLayoutEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    mesh.instanceMatrix.setUsage(DynamicDrawUsage)
    mesh.raycast = () => null
  }, [])

  useFrame((state) => {
    const mesh = ref.current
    if (!mesh) return
    const t = state.clock.elapsedTime
    const count = sim.count
    const selected = useWorldStore.getState().selectedAnt
    const camX = state.camera.position.x
    const camZ = state.camera.position.z

    const P = sim.positions
    const V = sim.velocities

    for (let i = 0; i < count; i++) {
      const i3 = i * 3
      const px = P[i3]
      const py = P[i3 + 1]
      const pz = P[i3 + 2]

      const dx = px - camX
      const dz = pz - camZ
      const far = dx * dx + dz * dz > 160 * 160

      const yaw = Math.atan2(V[i3], V[i3 + 2])
      const speed = Math.hypot(V[i3], V[i3 + 2])

      const bob = far ? 0 : Math.sin(t * 6 + sim.phase[i]) * 0.16
      const pitch = far ? 0 : Math.min(speed * 0.02, 0.3)
      _e.set(pitch, yaw, 0)
      _q.setFromEuler(_e)

      _p.set(px, py + bob, pz)
      const sel = i === selected
      const task = sim.tasks[i] as AntTask
      const queenMul = task === AntTask.Queen ? 1.9 : 1
      const sc = BASE_SCALE * queenMul * (sel ? 1.7 : 1)
      _s.set(sc, sc, sc)
      _m.compose(_p, _q, _s)
      mesh.setMatrixAt(i, _m)

      // Natural ant bodies first; colony identity is a subtle tint, not candy.
      _c.copy(BODY).lerp(AMBER, 0.25)
      _c.lerp(COLONY_COLORS[sim.colonyId[i] % COLONY_COLORS.length], 0.16)
      if (task === AntTask.Queen) _c.lerp(GOLD, 0.35)
      else if (task === AntTask.Soldier) _c.lerp(SOLDIER, 0.28)
      if (sim.carrying[i]) _c.lerp(FOOD_GLOW, 0.36)
      if (sim.verified[i]) _c.lerp(VERIFIED_COLOR, 0.16)
      const hl = sim.highlight[i]
      if (hl > 0) _c.lerp(SELECT, hl * 0.5)
      if (sel) _c.copy(SELECT)
      mesh.setColorAt(i, _c)
    }

    mesh.count = count
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh
      ref={ref}
      args={[geometry, undefined, MAX_AGENTS]}
      frustumCulled={false}
      castShadow
      key={agentCount}
    >
      <meshStandardMaterial roughness={0.55} metalness={0.05} toneMapped />
    </instancedMesh>
  )
}
