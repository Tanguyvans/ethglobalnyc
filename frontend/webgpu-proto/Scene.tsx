import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
// IMPORTANT: lights must come from the SAME three build as the WebGPURenderer
// (three/webgpu), otherwise the node light system logs
// "LightsNode.setupNodeLights: Light node not found" and the scene renders
// unlit. R3F's JSX <ambientLight/> would instantiate the WebGL `three` build's
// class, which the node renderer does not recognise.
import {
  AmbientLight as GPUAmbientLight,
  HemisphereLight as GPUHemisphereLight,
  DirectionalLight as GPUDirectionalLight,
} from 'three/webgpu'
import {
  makeTerrainMaterial,
  makeSkyMaterial,
  makeWaterMaterial,
  makeAntMaterial,
  TERRAIN_AMPLITUDE,
  TERRAIN_SCALE,
} from './tslMaterials'

const ROLE_COLORS = ['#34e07a', '#3ab4ff', '#ffa53a', '#b07cff', '#ff5e9c'].map(
  (h) => new THREE.Color(h),
)

/** CPU height sampler mirroring the TSL fbm so ants sit on the terrain. */
function fbm(x: number, z: number) {
  // cheap value-ish noise (not identical to mx_noise_float, but close enough
  // to keep ants near the surface for the demo).
  let n = 0,
    amp = 0.5,
    freq = 1
  for (let i = 0; i < 4; i++) {
    const v =
      Math.sin(x * freq * 1.3 + 1.7) * Math.cos(z * freq * 1.1 - 0.6) +
      Math.sin((x + z) * freq * 0.7)
    n += (v * 0.5) * amp
    amp *= 0.5
    freq *= 2
  }
  return n
}
const heightAt = (wx: number, wz: number) =>
  fbm(wx * TERRAIN_SCALE, wz * TERRAIN_SCALE) * TERRAIN_AMPLITUDE

export function Scene() {
  const skyMat = useMemo(makeSkyMaterial, [])
  const terrainMat = useMemo(makeTerrainMaterial, [])
  const waterMat = useMemo(makeWaterMaterial, [])
  const antMat = useMemo(makeAntMaterial, [])

  const terrainGeo = useMemo(() => {
    // NOTE: do NOT bake rotateX here. The TSL material displaces positionLocal.z
    // (=height) and samples noise on positionLocal.xy (the plane surface). The
    // mesh is rotated -90deg X via the `rotation` prop so local +Z -> world +Y.
    return new THREE.PlaneGeometry(200, 200, 256, 256)
  }, [])
  const skyGeo = useMemo(() => new THREE.SphereGeometry(400, 32, 16), [])
  const waterGeo = useMemo(() => {
    return new THREE.PlaneGeometry(200, 200, 64, 64)
  }, [])

  // ---- Instanced ants ----
  const COUNT = 400
  const antRef = useRef<THREE.InstancedMesh>(null)
  const COLORS = useMemo(() => new Float32Array(COUNT * 3), [])
  const antGeo = useMemo(() => {
    const g = new THREE.ConeGeometry(0.5, 1.4, 6)
    // Bind the per-instance color buffer directly on the geometry as an
    // InstancedBufferAttribute named "instanceColor". The TSL node
    // attribute('instanceColor') resolves against geometry attributes, so this
    // is the reliable cross-build way to feed per-instance color into WebGPU
    // (setColorAt's mesh.instanceColor is NOT auto-wired by the node system).
    g.setAttribute('instanceColor', new THREE.InstancedBufferAttribute(COLORS, 3))
    return g
  }, [COLORS])
  const seeds = useMemo(
    () =>
      Array.from({ length: COUNT }, () => ({
        x: (Math.random() - 0.5) * 160,
        z: (Math.random() - 0.5) * 160,
        phase: Math.random() * Math.PI * 2,
        speed: 0.3 + Math.random() * 0.7,
        role: Math.floor(Math.random() * ROLE_COLORS.length),
      })),
    [],
  )

  // Lights from the three/webgpu build (see import note).
  const lights = useMemo(() => {
    const amb = new GPUAmbientLight(new THREE.Color('#cfe6ff'), 1.1)
    const hemi = new GPUHemisphereLight(
      new THREE.Color('#bfe0ff'),
      new THREE.Color('#6b6350'),
      0.8,
    )
    const dir = new GPUDirectionalLight(new THREE.Color('#fff1cf'), 2.0)
    dir.position.set(60, 90, 40)
    return { amb, hemi, dir }
  }, [])

  // set per-instance colors once
  const colorsSet = useRef(false)
  useFrame((state) => {
    const mesh = antRef.current
    if (!mesh) return
    if (!colorsSet.current) {
      for (let i = 0; i < COUNT; i++) {
        const c = ROLE_COLORS[seeds[i].role]
        COLORS[i * 3] = c.r
        COLORS[i * 3 + 1] = c.g
        COLORS[i * 3 + 2] = c.b
      }
      ;(antGeo.getAttribute('instanceColor') as THREE.BufferAttribute).needsUpdate = true
      colorsSet.current = true
    }
    const t = state.clock.elapsedTime
    const m = new THREE.Matrix4()
    for (let i = 0; i < COUNT; i++) {
      const s = seeds[i]
      const wx = s.x + Math.sin(t * s.speed + s.phase) * 6
      const wz = s.z + Math.cos(t * s.speed * 0.8 + s.phase) * 6
      const wy = heightAt(wx, wz) + 0.7
      m.makeTranslation(wx, wy, wz)
      mesh.setMatrixAt(i, m)
    }
    mesh.instanceMatrix.needsUpdate = true
  })

  return (
    <>
      {/* atmospheric lighting (three/webgpu build) => no black shadows */}
      <primitive object={lights.amb} />
      <primitive object={lights.hemi} />
      <primitive object={lights.dir} />

      <mesh geometry={skyGeo} material={skyMat} />
      <mesh
        geometry={terrainGeo}
        material={terrainMat}
        rotation={[-Math.PI / 2, 0, 0]}
      />
      <mesh
        geometry={waterGeo}
        material={waterMat}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.6, 0]}
      />

      <instancedMesh
        ref={antRef}
        args={[antGeo, antMat, COUNT]}
      />
    </>
  )
}

/** Slow orbit so the screenshot shows depth + parallax. */
export function CameraRig() {
  const { camera } = useThree()
  useFrame((state) => {
    const t = state.clock.elapsedTime * 0.08
    camera.position.set(Math.sin(t) * 70, 38, Math.cos(t) * 70)
    camera.lookAt(0, 2, 0)
  })
  return null
}
