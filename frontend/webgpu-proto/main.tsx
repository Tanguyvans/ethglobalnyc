import { StrictMode, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Canvas } from '@react-three/fiber'
import * as THREE from 'three'
import type { WebGPURenderer } from 'three/webgpu'
import { makeWebGPURenderer, probeWebGPU } from './webgpuRenderer'
import { Scene, CameraRig } from './Scene'

function setStatus(s: string) {
  const el = document.getElementById('status')
  if (el) el.textContent = s
  // Also expose to the page for Playwright assertions.
  ;(window as any).__WEBGPU_PROTO_STATUS = s
}

function App() {
  const [ready, setReady] = useState(false)
  const [probe, setProbe] = useState<{ ok: boolean; reason?: string } | null>(null)
  const initialised = useRef(false)

  useEffect(() => {
    probeWebGPU().then((p) => {
      setProbe(p)
      setStatus(
        p.ok
          ? 'WebGPU adapter OK — creating WebGPURenderer…'
          : `WebGPU unavailable: ${p.reason}. WebGPURenderer will try WebGL2 fallback.`,
      )
      setReady(true)
    })
  }, [])

  if (!ready || !probe) return null

  const glFactory = makeWebGPURenderer({
    // If WebGPU adapter is missing, WebGPURenderer auto-falls-back to its
    // WebGL2 backend; we still report the backend that actually came up.
    onInit: (renderer: WebGPURenderer) => {
      initialised.current = true
      const backend = (renderer as any).backend
      const isWebGPU = backend?.isWebGPUBackend === true
      setStatus(
        `renderer initialised — backend: ${isWebGPU ? 'WebGPU' : 'WebGL2 (fallback)'}` +
          `\nframes rendering. ants=400`,
      )
      ;(window as any).__WEBGPU_PROTO_BACKEND = isWebGPU ? 'webgpu' : 'webgl2'
      ;(window as any).__WEBGPU_PROTO_INITED = true
    },
    onError: (err) => {
      setStatus('renderer init FAILED: ' + (err as Error).message)
      ;(window as any).__WEBGPU_PROTO_ERROR = (err as Error).message
    },
  })

  return (
    <Canvas
      // R3F 8 calls this factory synchronously and uses the returned renderer
      // (which has `.render`) directly. See webgpuRenderer.ts for the why.
      gl={glFactory as any}
      // colorManagement + camera
      camera={{ position: [70, 38, 70], fov: 50, near: 0.1, far: 1000 }}
      // R3F's shadowMap toggle is a no-op shape WebGPURenderer also exposes.
      shadows={false}
      onCreated={(state) => {
        const scene = state.scene
        scene.fog = new THREE.Fog(new THREE.Color('#dcefff'), 60, 320)
        scene.background = new THREE.Color('#9fd0ff')
        // tone mapping for the soft atmospheric look
        ;(state.gl as any).toneMapping = THREE.ACESFilmicToneMapping
        ;(state.gl as any).toneMappingExposure = 1.05
      }}
    >
      <Scene />
      <CameraRig />
    </Canvas>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
