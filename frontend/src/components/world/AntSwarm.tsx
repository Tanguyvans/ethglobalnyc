/**
 * AntSwarm — every agent from ONE InstancedMesh with per-instance color. The
 * body is a blocky, voxel-style ant (merged boxes: abdomen + thorax + head +
 * legs) pointing +Z, oriented by velocity each frame. Matrices + colors are
 * written straight from the simStore typed arrays — zero per-frame allocation.
 *
 * Not raycast directly (picking goes through ground + spatial hash).
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import {
  InstancedMesh,
  BoxGeometry,
  Matrix4,
  Quaternion,
  Vector3,
  Euler,
  Color,
  DynamicDrawUsage,
} from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { sim, MAX_AGENTS } from '../../store/simStore'
import { Role } from '../../data/schema'
import { ROLE_COLORS, VERIFIED_COLOR } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'

const _m = new Matrix4()
const _q = new Quaternion()
const _e = new Euler()
const _p = new Vector3()
const _s = new Vector3()
const _c = new Color()
const SELECT = new Color('#ffffff')

const BASE_SCALE = 1.7

/** Build a blocky ant facing +Z, centered near origin, ~1.6 units long. */
function buildAntGeometry() {
  const part = (w: number, h: number, d: number, x: number, y: number, z: number) => {
    const g = new BoxGeometry(w, h, d)
    g.translate(x, y, z)
    return g
  }
  const parts = [
    part(0.7, 0.62, 0.9, 0, 0.0, -0.55), // abdomen (rear)
    part(0.5, 0.5, 0.6, 0, 0.05, 0.1), // thorax
    part(0.46, 0.46, 0.46, 0, 0.12, 0.66), // head (front)
    part(0.12, 0.12, 0.5, 0, 0.32, 0.92), // antennae stub
    // legs (thin slabs to the sides)
    part(1.1, 0.1, 0.12, 0, -0.18, 0.2),
    part(1.1, 0.1, 0.12, 0, -0.18, -0.1),
    part(1.0, 0.1, 0.12, 0, -0.18, -0.4),
  ]
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

      const bob = far ? 0 : Math.sin(t * 6 + sim.phase[i]) * 0.18
      const pitch = far ? 0 : Math.min(speed * 0.02, 0.3)
      _e.set(pitch, yaw, 0)
      _q.setFromEuler(_e)

      _p.set(px, py + bob, pz)
      const sel = i === selected
      const sc = BASE_SCALE * (sel ? 1.7 : 1)
      _s.set(sc, sc, sc)
      _m.compose(_p, _q, _s)
      mesh.setMatrixAt(i, _m)

      _c.copy(ROLE_COLORS[sim.roles[i] as Role])
      if (sim.verified[i]) _c.lerp(VERIFIED_COLOR, 0.6)
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
      <meshStandardMaterial roughness={0.6} metalness={0.0} toneMapped />
    </instancedMesh>
  )
}
