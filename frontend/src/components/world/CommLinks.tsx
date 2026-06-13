/**
 * CommLinks — communication pulses (debate claims) rendered from commBuffer.
 * One InstancedMesh of additive glow sprites; each active pulse is a single
 * instance travelling along its source→destination path, fading over its life.
 * The buffer is updated by Engine; this component only reads + draws it.
 */

import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { InstancedMesh, Matrix4, Vector3, Color, AdditiveBlending, SphereGeometry } from 'three'
import { commBuffer, MAX_PULSES } from '../../systems/commBuffer'

const _m = new Matrix4()
const _p = new Vector3()
const _c = new Color()
const COOL = new Color('#3abeff') // away-leaning
const WARM = new Color('#ffd166') // home-leaning

export default function CommLinks() {
  const ref = useRef<InstancedMesh>(null)
  const geometry = useMemo(() => new SphereGeometry(0.5, 8, 8), [])

  useFrame(() => {
    const mesh = ref.current
    if (!mesh) return
    for (let i = 0; i < MAX_PULSES; i++) {
      if (!commBuffer.active[i]) {
        _m.makeScale(0, 0, 0)
        mesh.setMatrixAt(i, _m)
        continue
      }
      const k = commBuffer.t[i] / commBuffer.life[i] // 0..1 progress
      // ease along path
      const x = commBuffer.ax[i] + (commBuffer.bx[i] - commBuffer.ax[i]) * k
      const y = commBuffer.ay[i] + (commBuffer.by[i] - commBuffer.ay[i]) * k + Math.sin(k * Math.PI) * 2
      const z = commBuffer.az[i] + (commBuffer.bz[i] - commBuffer.az[i]) * k
      _p.set(x, y, z)
      // fade in then out (bell), scale follows
      const fade = Math.sin(k * Math.PI)
      const sc = 0.4 + fade * 0.9
      _m.makeScale(sc, sc, sc)
      _m.setPosition(_p)
      mesh.setMatrixAt(i, _m)

      _c.copy(COOL).lerp(WARM, commBuffer.hue[i])
      _c.multiplyScalar(0.6 + fade * 0.8)
      mesh.setColorAt(i, _c)
    }
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh ref={ref} args={[geometry, undefined, MAX_PULSES]} frustumCulled={false}>
      <meshBasicMaterial
        transparent
        opacity={0.9}
        blending={AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </instancedMesh>
  )
}
