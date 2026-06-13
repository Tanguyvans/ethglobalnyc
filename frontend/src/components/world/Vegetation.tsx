/**
 * Vegetation — deterministic instanced scatter that dresses the terrain:
 *   • Trees   (trunk + conifer canopy) on gentle grass slopes above the shore
 *   • Rocks   (faceted boulders) on steep faces and high ground
 *   • Shrubs  (small bushes) sprinkled across the lowlands
 * Each kind is a single InstancedMesh (one draw call). Built once from the
 * shared terrainHeight()/terrainSlope() so everything sits flush on the ground.
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import {
  InstancedMesh,
  Matrix4,
  Quaternion,
  Vector3,
  Euler,
  Color,
  CylinderGeometry,
  ConeGeometry,
  IcosahedronGeometry,
} from 'three'
import { terrainHeight, terrainSlope, WATER_LEVEL } from '../../utils/noise'
import { PALETTE } from '../../utils/palette'
import { mulberry32 } from '../../utils/math'

const SCATTER_HALF = 320 // place props within this radius of origin
const GRID = 110 // candidate samples per axis (12k candidates)

const _m = new Matrix4()
const _p = new Vector3()
const _q = new Quaternion()
const _e = new Euler()
const _s = new Vector3()
const _c = new Color()

type Placement = { x: number; y: number; z: number; scale: number; yaw: number }

function scatter() {
  const rand = mulberry32(20260613)
  const trees: Placement[] = []
  const rocks: Placement[] = []
  const shrubs: Placement[] = []
  const step = (SCATTER_HALF * 2) / GRID
  for (let gx = 0; gx < GRID; gx++) {
    for (let gz = 0; gz < GRID; gz++) {
      const x = -SCATTER_HALF + gx * step + (rand() - 0.5) * step
      const z = -SCATTER_HALF + gz * step + (rand() - 0.5) * step
      // keep a clearing around the colony at origin
      if (x * x + z * z < 42 * 42) continue
      const y = terrainHeight(x, z)
      if (y < WATER_LEVEL + 1.2) continue // no props in/under water
      const slope = terrainSlope(x, z)
      const yaw = rand() * Math.PI * 2
      if (slope > 0.5 || y > 22) {
        // rocky / high ground -> boulders (sparse)
        if (rand() < 0.5) rocks.push({ x, y, z, scale: 0.6 + rand() * 1.8, yaw })
      } else if (y < 18 && slope < 0.4) {
        const r = rand()
        if (r < 0.34) trees.push({ x, y, z, scale: 0.75 + rand() * 0.7, yaw })
        else if (r < 0.62) shrubs.push({ x, y, z, scale: 0.7 + rand() * 0.9, yaw })
      }
    }
  }
  return { trees, rocks, shrubs }
}

export default function Vegetation() {
  const trunkRef = useRef<InstancedMesh>(null)
  const canopyRef = useRef<InstancedMesh>(null)
  const rockRef = useRef<InstancedMesh>(null)
  const shrubRef = useRef<InstancedMesh>(null)

  const { trees, rocks, shrubs } = useMemo(scatter, [])

  const trunkGeo = useMemo(() => new CylinderGeometry(0.32, 0.55, 4.2, 5), [])
  const canopyGeo = useMemo(() => new ConeGeometry(2.6, 8.5, 7), [])
  const rockGeo = useMemo(() => new IcosahedronGeometry(1.5, 0), [])
  const shrubGeo = useMemo(() => new IcosahedronGeometry(1.3, 0), [])

  const trunkColor = useMemo(() => new Color('#6b4a2f'), [])
  const canopyBase = useMemo(() => new Color('#2f6e2c'), [])
  const rockColor = useMemo(() => new Color(PALETTE.rock), [])
  const shrubBase = useMemo(() => new Color('#4f8f3c'), [])

  useLayoutEffect(() => {
    const rand = mulberry32(7) // per-instance tonal jitter
    // trees: trunk + canopy share the placement
    if (trunkRef.current && canopyRef.current) {
      trees.forEach((t, i) => {
        const sc = t.scale
        _q.setFromEuler(_e.set(0, t.yaw, 0))
        // trunk
        _s.set(sc, sc, sc)
        _p.set(t.x, t.y + 2.1 * sc, t.z)
        _m.compose(_p, _q, _s)
        trunkRef.current!.setMatrixAt(i, _m)
        trunkRef.current!.setColorAt(i, trunkColor)
        // canopy sits on top of the trunk
        _p.set(t.x, t.y + (4.2 + 8.5 / 2 - 1.2) * sc, t.z)
        _m.compose(_p, _q, _s)
        canopyRef.current!.setMatrixAt(i, _m)
        const v = 0.82 + rand() * 0.3
        _c.copy(canopyBase).multiplyScalar(v)
        canopyRef.current!.setColorAt(i, _c)
      })
      trunkRef.current.count = trees.length
      canopyRef.current.count = trees.length
      trunkRef.current.instanceMatrix.needsUpdate = true
      canopyRef.current.instanceMatrix.needsUpdate = true
      if (trunkRef.current.instanceColor) trunkRef.current.instanceColor.needsUpdate = true
      if (canopyRef.current.instanceColor) canopyRef.current.instanceColor.needsUpdate = true
    }
    // rocks
    if (rockRef.current) {
      rocks.forEach((r, i) => {
        _e.set(rand() * 0.6, r.yaw, rand() * 0.6)
        _q.setFromEuler(_e)
        _s.set(r.scale, r.scale * (0.6 + rand() * 0.5), r.scale)
        _p.set(r.x, r.y + r.scale * 0.4, r.z)
        _m.compose(_p, _q, _s)
        rockRef.current!.setMatrixAt(i, _m)
        const v = 0.8 + rand() * 0.35
        _c.copy(rockColor).multiplyScalar(v)
        rockRef.current!.setColorAt(i, _c)
      })
      rockRef.current.count = rocks.length
      rockRef.current.instanceMatrix.needsUpdate = true
      if (rockRef.current.instanceColor) rockRef.current.instanceColor.needsUpdate = true
    }
    // shrubs
    if (shrubRef.current) {
      shrubs.forEach((b, i) => {
        _q.setFromEuler(_e.set(0, b.yaw, 0))
        _s.set(b.scale, b.scale * 0.8, b.scale)
        _p.set(b.x, b.y + b.scale * 0.5, b.z)
        _m.compose(_p, _q, _s)
        shrubRef.current!.setMatrixAt(i, _m)
        const v = 0.78 + rand() * 0.34
        _c.copy(shrubBase).multiplyScalar(v)
        shrubRef.current!.setColorAt(i, _c)
      })
      shrubRef.current.count = shrubs.length
      shrubRef.current.instanceMatrix.needsUpdate = true
      if (shrubRef.current.instanceColor) shrubRef.current.instanceColor.needsUpdate = true
    }
  }, [trees, rocks, shrubs, trunkColor, canopyBase, rockColor, shrubBase])

  return (
    <group>
      <instancedMesh ref={trunkRef} args={[trunkGeo, undefined, Math.max(trees.length, 1)]} castShadow receiveShadow frustumCulled={false}>
        <meshStandardMaterial vertexColors roughness={0.95} metalness={0} />
      </instancedMesh>
      <instancedMesh ref={canopyRef} args={[canopyGeo, undefined, Math.max(trees.length, 1)]} castShadow receiveShadow frustumCulled={false}>
        <meshStandardMaterial vertexColors roughness={0.85} metalness={0} flatShading />
      </instancedMesh>
      <instancedMesh ref={rockRef} args={[rockGeo, undefined, Math.max(rocks.length, 1)]} castShadow receiveShadow frustumCulled={false}>
        <meshStandardMaterial vertexColors roughness={1} metalness={0} flatShading />
      </instancedMesh>
      <instancedMesh ref={shrubRef} args={[shrubGeo, undefined, Math.max(shrubs.length, 1)]} castShadow receiveShadow frustumCulled={false}>
        <meshStandardMaterial vertexColors roughness={0.9} metalness={0} flatShading />
      </instancedMesh>
    </group>
  )
}
