/**
 * Colony — renders every nest in the ecosystem. Each is a noise-displaced dirt
 * mound with a crater entrance, a glowing queen-core + health ring in the
 * colony's identity hue, and a pale brood pile that swells with `brood`. Core
 * glow + ring track colony health; the mound scales with population. Clicking a
 * nest selects that colony.
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
import { groundY, noise2D } from '../../utils/noise'
import { PALETTE, COLONY_COLORS } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'

const BASE_R = 22
const FLATTEN = 0.5

function buildMound(seed: number) {
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
    const d = noise2D(dir.x * 3 + seed, dir.z * 3 - seed) * 2.6 + noise2D(dir.x * 7, dir.z * 7) * 1.1
    v.addScaledVector(dir, d)
    v.y *= FLATTEN
    pos.setXYZ(i, v.x, v.y, v.z)
    c.copy(dirt).lerp(grass, Math.max(0, 0.55 - dir.y) * 0.7)
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
}

function ColonyNest({ index }: { index: number }) {
  const coreRef = useRef<Mesh>(null)
  const ringRef = useRef<Mesh>(null)
  const broodRef = useRef<Mesh>(null)

  const colony = sim.colonies[index]
  const hue = COLONY_COLORS[index % COLONY_COLORS.length]
  const HOT = useMemo(() => new Color('#ffffff'), [])

  const moundGeo = useMemo(() => buildMound(5 + index * 13), [index])
  const moundMat = useMemo(
    () => new MeshStandardMaterial({ vertexColors: true, roughness: 1, metalness: 0 }),
    [],
  )
  const coreMat = useMemo(
    () =>
      new MeshStandardMaterial({
        color: '#fff4e2',
        emissive: hue.clone(),
        emissiveIntensity: 1.6,
        roughness: 0.3,
        toneMapped: false,
      }),
    [hue],
  )
  const ringMat = useMemo(
    () =>
      new MeshStandardMaterial({
        color: hue.clone(),
        emissive: hue.clone(),
        emissiveIntensity: 1.4,
        transparent: true,
        opacity: 0.7,
        toneMapped: false,
      }),
    [hue],
  )
  const broodMat = useMemo(
    () => new MeshStandardMaterial({ color: '#f3e6c8', emissive: '#caa56a', emissiveIntensity: 0.3, roughness: 0.6 }),
    [],
  )

  const base = useMemo(() => groundY(colony.x, colony.z), [colony.x, colony.z])
  const summitY = base + BASE_R * FLATTEN * 2 - 1
  const moundY = base + BASE_R * FLATTEN - 4

  useLayoutEffect(() => {
    if (coreRef.current) coreRef.current.position.y = summitY + 2
  }, [summitY])

  useFrame((state) => {
    const c = sim.colonies[index]
    if (!c) return
    const t = state.clock.elapsedTime
    const health = c.health
    if (coreRef.current) {
      const pulse = 1 + Math.sin(t * 2 + index) * 0.08
      coreRef.current.scale.setScalar(pulse * (1 + health * 0.6))
      coreRef.current.rotation.y = t * 0.5
      coreMat.emissiveIntensity = 1.3 + health * 2.2 + Math.sin(t * 4) * 0.25
      coreMat.emissive.copy(hue).lerp(HOT, health * 0.35)
    }
    if (ringRef.current) {
      ringRef.current.rotation.z = t * 0.5
      ringRef.current.rotation.x = Math.PI / 2 + Math.sin(t * 0.3) * 0.12
      ringRef.current.scale.setScalar(1 + health * 0.6)
      ringMat.opacity = 0.4 + health * 0.5
    }
    if (broodRef.current) {
      const b = Math.min(2.2, 0.4 + c.brood * 0.05)
      broodRef.current.scale.set(b, b * 0.5, b)
    }
  })

  const onSelect = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    useWorldStore.getState().selectColony(index)
  }

  return (
    <group position={[colony.x, 0, colony.z]}>
      <mesh geometry={moundGeo} material={moundMat} position={[0, moundY, 0]} castShadow receiveShadow onClick={onSelect} />
      {/* crater entrance */}
      <mesh position={[0, summitY - 1.5, 0]} rotation={[-Math.PI / 2, 0, 0]} onClick={onSelect}>
        <circleGeometry args={[6, 24]} />
        <meshStandardMaterial color="#1c1208" roughness={1} />
      </mesh>
      {/* brood pile in the crater */}
      <mesh ref={broodRef} material={broodMat} position={[0, summitY - 0.8, 0]}>
        <icosahedronGeometry args={[3, 1]} />
      </mesh>
      {/* glowing queen-core */}
      <mesh ref={coreRef} position={[0, summitY + 2, 0]} material={coreMat} onClick={onSelect} castShadow>
        <icosahedronGeometry args={[4, 1]} />
      </mesh>
      {/* health ring */}
      <mesh ref={ringRef} position={[0, summitY + 2, 0]} material={ringMat}>
        <torusGeometry args={[11, 0.6, 10, 48]} />
      </mesh>
      <pointLight position={[0, summitY + 4, 0]} color={hue} intensity={2.2} distance={120} decay={1.4} />
    </group>
  )
}

export default function Colony() {
  // re-read after each sim.init() (which is driven by the population control)
  const agentCount = useWorldStore((s) => s.agentCount)
  return (
    <group key={agentCount}>
      {sim.colonies.map((_, i) => (
        <ColonyNest key={i} index={i} />
      ))}
    </group>
  )
}
