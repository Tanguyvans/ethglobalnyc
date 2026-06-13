/**
 * Terrain — a smooth, displaced height-mesh built from the SAME terrainHeight()
 * the simulation samples, so ants/colony/camera ride exactly this surface.
 * Vertices are colored by altitude + slope (sand → grass → rock → snow, with
 * cliffs going rocky) and lit with smooth normals; the realistic sky, sun,
 * shadows and fog do the rest. A single click raycast resolves a world point
 * handed to the spatial-hash ant picker.
 */

import { useMemo, useRef } from 'react'
import { type ThreeEvent } from '@react-three/fiber'
import { PlaneGeometry, BufferAttribute, Color, Mesh } from 'three'
import { terrainHeight, terrainSlope, WATER_LEVEL } from '../../utils/noise'
import { biomeColor, PALETTE } from '../../utils/palette'
import { noise2D } from '../../utils/noise'
import { pickAnt } from '../../systems/raycast'
import { useWorldStore } from '../../store/worldStore'

const SPAN = 1100 // world units the mesh covers (well past the play area)
const SEG = 240 // grid resolution; ~4.6 units/segment

export default function Terrain() {
  const ref = useRef<Mesh>(null)

  const geometry = useMemo(() => {
    const g = new PlaneGeometry(SPAN, SPAN, SEG, SEG)
    g.rotateX(-Math.PI / 2) // lie flat in XZ; +Y is up
    const pos = g.attributes.position as BufferAttribute
    const n = pos.count
    const colors = new Float32Array(n * 3)
    const c = new Color()
    for (let i = 0; i < n; i++) {
      const px = pos.getX(i)
      const pz = pos.getZ(i)
      const h = terrainHeight(px, pz)
      pos.setY(i, h)
      const slope = terrainSlope(px, pz)
      biomeColor(h, slope, c)
      // subtle per-vertex tonal variation so large faces aren't uniform
      const v = 0.92 + (noise2D(px * 0.3, pz * 0.3) * 0.5 + 0.5) * 0.16
      c.multiplyScalar(v)
      colors[i * 3] = c.r
      colors[i * 3 + 1] = c.g
      colors[i * 3 + 2] = c.b
    }
    pos.needsUpdate = true
    g.setAttribute('color', new BufferAttribute(colors, 3))
    g.computeVertexNormals()
    return g
  }, [])

  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    const i = pickAnt(e.point.x, e.point.z)
    const store = useWorldStore.getState()
    if (i !== null) store.selectAnt(i)
    else {
      store.selectAnt(null)
      store.selectColony(null)
    }
  }

  return (
    <>
      <mesh ref={ref} geometry={geometry} receiveShadow castShadow onClick={onClick}>
        <meshStandardMaterial vertexColors roughness={0.96} metalness={0} />
      </mesh>
      {/* distant seabed so the horizon under the water plane is never see-through */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, WATER_LEVEL - 6, 0]} receiveShadow>
        <planeGeometry args={[6000, 6000]} />
        <meshStandardMaterial color={PALETTE.waterDeep} roughness={1} />
      </mesh>
    </>
  )
}
