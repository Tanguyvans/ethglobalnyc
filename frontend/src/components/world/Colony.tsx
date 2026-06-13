/**
 * Colony — a natural anthill: an irregular oblate mound of dirt (noise-displaced
 * geodesic sphere, grass-dusted at the base) with a dark crater at the summit
 * holding a glowing energy core + rotating "health ring". Core glow + ring scale
 * track colony health (wealth + accuracy). Clicking the mound or core selects
 * the colony. Mound is static; core/ring animate.
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame, type ThreeEvent } from '@react-three/fiber'
import {
  IcosahedronGeometry,
  BufferAttribute,
  Mesh,
  MeshStandardMaterial,
  Color,
  Vector3,
} from 'three'
import { sim } from '../../store/simStore'
import { groundY } from '../../utils/noise'
import { noise2D } from '../../utils/noise'
import { PALETTE } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'

const BASE_R = 24
const FLATTEN = 0.5 // oblate factor (mound is wider than tall)
const CORE = new Color(PALETTE.verified)
const HOT = new Color('#ffffff')

export default function Colony() {
  const coreRef = useRef<Mesh>(null)
  const ringRef = useRef<Mesh>(null)

  const base = useMemo(() => groundY(0, 0), [])
  const summitY = base + BASE_R * FLATTEN * 2 - 1

  // irregular dirt mound geometry, built once
  const moundGeo = useMemo(() => {
    const g = new IcosahedronGeometry(BASE_R, 4)
    const pos = g.attributes.position as BufferAttribute
    const n = pos.count
    const colors = new Float32Array(n * 3)
    const dirt = new Color(PALETTE.dirt)
    const grass = new Color(PALETTE.grass)
    const c = new Color()
    const v = new Vector3()
    for (let i = 0; i < n; i++) {
      v.set(pos.getX(i), pos.getY(i), pos.getZ(i))
      const dir = v.clone().normalize()
      // lumpy displacement
      const d = noise2D(dir.x * 3 + 5, dir.z * 3 - 2) * 2.6 + noise2D(dir.x * 7, dir.z * 7) * 1.1
      v.addScaledVector(dir, d)
      v.y *= FLATTEN // flatten into a mound
      pos.setXYZ(i, v.x, v.y, v.z)
      // grass near the base, dirt up high; crater rim darker
      const up = dir.y
      c.copy(dirt).lerp(grass, Math.max(0, 0.55 - up) * 0.7)
      const shade = 0.8 + (noise2D(dir.x * 9, dir.z * 9) * 0.5 + 0.5) * 0.3
      c.multiplyScalar(shade)
      colors[i * 3] = c.r
      colors[i * 3 + 1] = c.g
      colors[i * 3 + 2] = c.b
    }
    pos.needsUpdate = true
    g.setAttribute('color', new BufferAttribute(colors, 3))
    g.computeVertexNormals()
    return g
  }, [])

  const moundMat = useMemo(
    () => new MeshStandardMaterial({ vertexColors: true, roughness: 1, metalness: 0 }),
    [],
  )
  const coreMat = useMemo(
    () =>
      new MeshStandardMaterial({
        color: '#fff1cc',
        emissive: CORE,
        emissiveIntensity: 1.6,
        roughness: 0.3,
        toneMapped: false,
      }),
    [],
  )
  const ringMat = useMemo(
    () =>
      new MeshStandardMaterial({
        color: CORE,
        emissive: CORE,
        emissiveIntensity: 1.4,
        transparent: true,
        opacity: 0.7,
        toneMapped: false,
      }),
    [],
  )

  // mound centered so its flattened bottom rests near the ground
  const moundY = base + BASE_R * FLATTEN - 4

  useLayoutEffect(() => {
    if (coreRef.current) coreRef.current.position.y = summitY + 2
  }, [summitY])

  useFrame((state) => {
    const c = sim.colonies[0]
    if (!c) return
    const t = state.clock.elapsedTime
    const health = c.health

    if (coreRef.current) {
      const pulse = 1 + Math.sin(t * 2) * 0.08
      coreRef.current.scale.setScalar(pulse * (1 + health * 0.6))
      coreRef.current.rotation.y = t * 0.5
      coreMat.emissiveIntensity = 1.4 + health * 2.4 + Math.sin(t * 4) * 0.25
      coreMat.emissive.copy(CORE).lerp(HOT, health * 0.4)
    }
    if (ringRef.current) {
      ringRef.current.rotation.z = t * 0.5
      ringRef.current.rotation.x = Math.PI / 2 + Math.sin(t * 0.3) * 0.12
      ringRef.current.scale.setScalar(1 + health * 0.6)
      ringMat.opacity = 0.4 + health * 0.5
    }
  })

  const onSelect = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    useWorldStore.getState().selectColony(0)
  }

  return (
    <group>
      {/* dirt mound */}
      <mesh
        geometry={moundGeo}
        material={moundMat}
        position={[0, moundY, 0]}
        castShadow
        receiveShadow
        onClick={onSelect}
      />
      {/* dark crater disc at the summit (nest entrance) */}
      <mesh position={[0, summitY - 1.5, 0]} rotation={[-Math.PI / 2, 0, 0]} onClick={onSelect}>
        <circleGeometry args={[6, 24]} />
        <meshStandardMaterial color="#1c1208" roughness={1} />
      </mesh>

      {/* glowing energy core in the crater */}
      <mesh ref={coreRef} position={[0, summitY + 2, 0]} material={coreMat} onClick={onSelect} castShadow>
        <icosahedronGeometry args={[4, 1]} />
      </mesh>
      {/* health ring */}
      <mesh ref={ringRef} position={[0, summitY + 2, 0]} material={ringMat}>
        <torusGeometry args={[11, 0.6, 10, 48]} />
      </mesh>
      <pointLight position={[0, summitY + 4, 0]} color={PALETTE.verified} intensity={2.4} distance={120} decay={1.4} />
    </group>
  )
}
