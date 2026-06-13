/**
 * CameraRig — the explore ↔ strategic camera state machine.
 *
 *   strategic : OrbitControls (mounted only in this state)
 *   explore   : PointerLockControls + WASD walk (mounted only in this state)
 *   transition: NEITHER controller; camera position + lookAt are damped toward
 *               the destination preset, then endTransition() flips the state.
 *
 * This guarantees only one controller is ever active and that every mode change
 * is a smooth lerp, never a hard cut (per the plan).
 */

import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, PointerLockControls } from '@react-three/drei'
import { Vector3 } from 'three'
import { damp3 } from 'maath/easing'
import { useWorldStore, type CameraTarget } from '../../store/worldStore'
import { groundY } from '../../utils/noise'

const EYE_HEIGHT = 3.5
const WALK_SPEED = 28
const SPRINT = 2.0

const PRESETS: Record<CameraTarget, { pos: Vector3; target: Vector3 }> = {
  strategic: { pos: new Vector3(62, 72, 98), target: new Vector3(0, 14, 0) },
  explore: { pos: new Vector3(0, 0, 60), target: new Vector3(0, 8, 0) },
}

export default function CameraRig() {
  const cameraMode = useWorldStore((s) => s.cameraMode)
  const targetMode = useWorldStore((s) => s.targetMode)
  const { camera, gl } = useThree()

  // live keyboard state (no React re-render)
  const keys = useRef<Record<string, boolean>>({})
  const lookTarget = useMemo(() => new Vector3(0, 8, 0), [])
  const forward = useMemo(() => new Vector3(), [])
  const right = useMemo(() => new Vector3(), [])

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      keys.current[e.code] = true
    }
    const up = (e: KeyboardEvent) => {
      keys.current[e.code] = false
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  // Prime the lookTarget when a transition begins so damping reads smoothly.
  useEffect(() => {
    if (cameraMode === 'transition') {
      lookTarget.copy(PRESETS[targetMode].target)
    }
  }, [cameraMode, targetMode, lookTarget])

  useFrame((_, dt) => {
    if (cameraMode === 'transition') {
      const dest = PRESETS[targetMode]
      damp3(camera.position, dest.pos, 0.35, dt)
      camera.lookAt(dest.target)
      if (camera.position.distanceToSquared(dest.pos) < 1.5) {
        camera.position.copy(dest.pos)
        useWorldStore.getState().endTransition()
      }
      return
    }

    if (cameraMode === 'explore') {
      // WASD walk along the ground plane using current facing
      camera.getWorldDirection(forward)
      forward.y = 0
      forward.normalize()
      right.crossVectors(forward, camera.up).normalize()

      const k = keys.current
      let mx = 0
      let mz = 0
      if (k['KeyW'] || k['ArrowUp']) mz += 1
      if (k['KeyS'] || k['ArrowDown']) mz -= 1
      if (k['KeyD'] || k['ArrowRight']) mx += 1
      if (k['KeyA'] || k['ArrowLeft']) mx -= 1
      if (mx !== 0 || mz !== 0) {
        const sp = WALK_SPEED * (k['ShiftLeft'] ? SPRINT : 1) * dt
        const len = Math.hypot(mx, mz)
        camera.position.addScaledVector(forward, (mz / len) * sp)
        camera.position.addScaledVector(right, (mx / len) * sp)
      }
      // glue eye height to the voxel surface
      camera.position.y = groundY(camera.position.x, camera.position.z) + EYE_HEIGHT
    }
  })

  return (
    <>
      {cameraMode === 'strategic' && (
        <OrbitControls
          makeDefault
          target={[0, 8, 0]}
          enablePan
          maxPolarAngle={Math.PI * 0.49}
          minDistance={20}
          maxDistance={320}
          enableDamping
          dampingFactor={0.08}
        />
      )}
      {cameraMode === 'explore' && <PointerLockControls makeDefault domElement={gl.domElement} />}
    </>
  )
}
