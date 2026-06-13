/**
 * StakeFlows — USDC stake particles (forecasts) rendered from flowBuffer. Each
 * active flow rides a quadratic curve between an agent and the colony; size =
 * stake, color = side (home green / away blue). Winners accelerate in (buffer
 * handles speed); losers fade out mid-path. Read-only over the buffer.
 */

import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { InstancedMesh, Matrix4, Vector3, Color, AdditiveBlending, SphereGeometry } from 'three'
import { flowBuffer, MAX_FLOWS } from '../../systems/flowBuffer'

const _m = new Matrix4()
const _p = new Vector3()
const _c = new Color()
const HOME = new Color('#2eff7a')
const AWAY = new Color('#3abeff')

export default function StakeFlows() {
  const ref = useRef<InstancedMesh>(null)
  const geometry = useMemo(() => new SphereGeometry(0.4, 8, 8), [])

  useFrame(() => {
    const mesh = ref.current
    if (!mesh) return
    for (let i = 0; i < MAX_FLOWS; i++) {
      if (!flowBuffer.active[i]) {
        _m.makeScale(0, 0, 0)
        mesh.setMatrixAt(i, _m)
        continue
      }
      const k = Math.min(1, flowBuffer.t[i] / flowBuffer.life[i])
      const u = 1 - k
      // quadratic bezier A -> C -> B
      const x = u * u * flowBuffer.ax[i] + 2 * u * k * flowBuffer.cx[i] + k * k * flowBuffer.bx[i]
      const y = u * u * flowBuffer.ay[i] + 2 * u * k * flowBuffer.cy[i] + k * k * flowBuffer.by[i]
      const z = u * u * flowBuffer.az[i] + 2 * u * k * flowBuffer.cz[i] + k * k * flowBuffer.bz[i]
      _p.set(x, y, z)

      const win = flowBuffer.win[i] === 1
      const fade = win ? 1 : Math.max(0, 1 - k * 1.4) // losers fade mid-path
      const sc = flowBuffer.size[i] * (0.6 + fade * 0.8)
      _m.makeScale(sc, sc, sc)
      _m.setPosition(_p)
      mesh.setMatrixAt(i, _m)

      _c.copy(flowBuffer.side[i] >= 0 ? HOME : AWAY)
      _c.multiplyScalar(0.5 + fade * 0.9)
      mesh.setColorAt(i, _c)
    }
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh ref={ref} args={[geometry, undefined, MAX_FLOWS]} frustumCulled={false}>
      <meshBasicMaterial
        transparent
        opacity={0.95}
        blending={AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </instancedMesh>
  )
}
