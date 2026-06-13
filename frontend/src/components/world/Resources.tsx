/**
 * Resources — energy crystals (USDC stake pools) rendered as one InstancedMesh.
 * They float, rotate, and scale with remaining energy. There are only a handful,
 * so direct instanced raycasting for hover is cheap and fine here (unlike the
 * swarm). Hover sets worldStore.hoveredResource for the tooltip.
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame, type ThreeEvent } from '@react-three/fiber'
import { InstancedMesh, Matrix4, Quaternion, Vector3, Euler, Color, OctahedronGeometry } from 'three'
import { sim, MAX_RESOURCES } from '../../store/simStore'
import { PALETTE } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'

const _m = new Matrix4()
const _q = new Quaternion()
const _e = new Euler()
const _p = new Vector3()
const _s = new Vector3()
const _c = new Color()
const BASE = new Color(PALETTE.resource)
const BRIGHT = new Color('#fff0d0')

export default function Resources() {
  const ref = useRef<InstancedMesh>(null)

  const geometry = useMemo(() => new OctahedronGeometry(3.2, 0), [])

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
      const bob = Math.sin(t * 1.5 + i) * 0.8
      _p.set(r.x, r.y + 5 + bob, r.z)
      _e.set(t * 0.3 + i, t * 0.5 + i, 0)
      _q.setFromEuler(_e)
      const sc = 0.6 + r.energy * 1.0
      _s.set(sc, sc, sc)
      _m.compose(_p, _q, _s)
      mesh.setMatrixAt(i, _m)
      _c.copy(BASE).lerp(BRIGHT, r.energy * 0.6)
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
      onPointerMove={onMove}
      onPointerOut={onOut}
    >
      <meshStandardMaterial
        roughness={0.15}
        metalness={0.1}
        emissive={PALETTE.resource}
        emissiveIntensity={0.7}
        toneMapped={false}
      />
    </instancedMesh>
  )
}
