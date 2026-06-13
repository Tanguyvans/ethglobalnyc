/**
 * Atmosphere — soft natural daylight: warm sun, strong sky fill, and a little
 * drifting dust. The goal is readable terrain with no crushed-black forests.
 */

import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { BufferGeometry, BufferAttribute, Points, AdditiveBlending, DirectionalLight } from 'three'
import { VOXEL_HALF } from '../../utils/noise'
import { PALETTE } from '../../utils/palette'
import { mulberry32 } from '../../utils/math'

const DUST_COUNT = 320

export default function Atmosphere() {
  const dustRef = useRef<Points>(null)
  const sunRef = useRef<DirectionalLight>(null)

  const dustGeo = useMemo(() => {
    const rand = mulberry32(98765)
    const arr = new Float32Array(DUST_COUNT * 3)
    for (let i = 0; i < DUST_COUNT; i++) {
      arr[i * 3] = (rand() * 2 - 1) * VOXEL_HALF
      arr[i * 3 + 1] = 6 + rand() * 50
      arr[i * 3 + 2] = (rand() * 2 - 1) * VOXEL_HALF
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(arr, 3))
    return g
  }, [])

  useFrame((state) => {
    if (dustRef.current) {
      const t = state.clock.elapsedTime
      dustRef.current.rotation.y = t * 0.01
      dustRef.current.position.y = Math.sin(t * 0.25) * 1.5
    }
  })

  return (
    <>
      <hemisphereLight args={['#d8ecff', '#8d8a72', 1.25]} />
      <ambientLight intensity={0.62} />
      <directionalLight
        ref={sunRef}
        position={[120, 180, 90]}
        intensity={1.75}
        color={PALETTE.sun}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={20}
        shadow-camera-far={520}
        shadow-camera-left={-220}
        shadow-camera-right={220}
        shadow-camera-top={220}
        shadow-camera-bottom={-220}
        shadow-bias={-0.00025}
      />

      <points ref={dustRef} geometry={dustGeo}>
        <pointsMaterial
          size={0.6}
          color="#ffffff"
          transparent
          opacity={0.18}
          sizeAttenuation
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </>
  )
}
