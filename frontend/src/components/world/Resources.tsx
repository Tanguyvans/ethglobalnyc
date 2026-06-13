/**
 * Resources — natural food/seed piles instead of floating game crystals. Ants
 * forage from these low ground clusters, so they should read like part of the
 * environment, not yellow prototype markers.
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame, type ThreeEvent } from '@react-three/fiber'
import { InstancedMesh, Matrix4, Quaternion, Vector3, Euler, Color, SphereGeometry, BufferGeometry } from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { sim, MAX_RESOURCES } from '../../store/simStore'
import { useWorldStore } from '../../store/worldStore'

const _m = new Matrix4()
const _q = new Quaternion()
const _e = new Euler()
const _p = new Vector3()
const _s = new Vector3()
const _c = new Color()
const BASE = new Color('#8b6238')
const RIPE = new Color('#c99649')

function buildFoodPile() {
  const parts: BufferGeometry[] = []
  const offsets = [
    [-0.9, 0.18, -0.2, 0.62],
    [-0.25, 0.25, 0.35, 0.72],
    [0.55, 0.2, -0.1, 0.58],
    [0.15, 0.42, -0.55, 0.5],
    [0.85, 0.16, 0.45, 0.42],
    [-0.65, 0.12, 0.55, 0.38],
  ] as const

  for (const [x, y, z, r] of offsets) {
    const g = new SphereGeometry(r, 8, 6)
    g.scale(1.15, 0.55, 0.9)
    g.translate(x, y, z)
    parts.push(g)
  }

  const merged = mergeGeometries(parts, false)!
  parts.forEach((p) => p.dispose())
  return merged
}

export default function Resources() {
  const ref = useRef<InstancedMesh>(null)
  const geometry = useMemo(buildFoodPile, [])

  useLayoutEffect(() => {
    if (ref.current) ref.current.instanceMatrix.needsUpdate = true
  }, [])

  useFrame((state) => {
    const mesh = ref.current
    if (!mesh) return
    const t = state.clock.elapsedTime
    const n = Math.min(sim.resources.length, MAX_RESOURCES)
    for (let i = 0; i < n; i++) {
      const r = sim.resources[i]
      _p.set(r.x, r.y + 0.12, r.z)
      _e.set(0.05, i * 1.618 + Math.sin(t * 0.08 + i) * 0.03, 0)
      _q.setFromEuler(_e)
      const sc = 1.15 + r.energy * 1.15
      _s.set(sc, sc, sc)
      _m.compose(_p, _q, _s)
      mesh.setMatrixAt(i, _m)
      _c.copy(BASE).lerp(RIPE, r.energy * 0.65)
      mesh.setColorAt(i, _c)
    }
    mesh.count = n
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  const onMove = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    if (e.instanceId !== undefined) useWorldStore.getState().setHoveredResource(e.instanceId)
  }
  const onOut = () => useWorldStore.getState().setHoveredResource(null)

  return (
    <instancedMesh
      ref={ref}
      args={[geometry, undefined, MAX_RESOURCES]}
      frustumCulled={false}
      castShadow
      receiveShadow
      onPointerMove={onMove}
      onPointerOut={onOut}
    >
      <meshStandardMaterial vertexColors roughness={0.92} metalness={0} />
    </instancedMesh>
  )
}
