/**
 * HUD — screen-space DOM overlay (outside the Canvas): brand, camera + data
 * controls, population slider, legend, FPS, and key hints. Also owns the V/Tab
 * keyboard shortcut for the camera mode toggle.
 *
 * Camera switches go through beginTransition() so the rig lerps (never cuts).
 */

import { useEffect } from 'react'
import { useWorldStore, type CameraMode, type CameraTarget } from '../../store/worldStore'
import { Role } from '../../data/schema'
import { ROLE_LABELS, ROLE_HEX, PALETTE } from '../../utils/palette'

const ROLES: Role[] = [Role.Worker, Role.Explorer, Role.Carrier, Role.Builder, Role.Messenger]

export default function HUD() {
  const cameraMode = useWorldStore((s) => s.cameraMode)
  const targetMode = useWorldStore((s) => s.targetMode)
  const dataSource = useWorldStore((s) => s.dataSource)
  const replayActive = useWorldStore((s) => s.replayActive)
  const agentCount = useWorldStore((s) => s.agentCount)
  const fps = useWorldStore((s) => s.fps)

  const beginTransition = useWorldStore((s) => s.beginTransition)
  const toggleCamera = useWorldStore((s) => s.toggleCamera)
  const setDataSource = useWorldStore((s) => s.setDataSource)
  const setAgentCount = useWorldStore((s) => s.setAgentCount)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'KeyV' || e.code === 'Tab') {
        e.preventDefault()
        toggleCamera()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggleCamera])

  // The mode shown as active during a transition is the destination.
  const shownMode: CameraMode = cameraMode === 'transition' ? targetMode : cameraMode
  const setMode = (m: CameraTarget) => {
    if (shownMode !== m && cameraMode !== 'transition') beginTransition(m)
  }

  return (
    <div className="hud">
      <div className="hud-top">
        <div className="glass brand">
          <h1>COLONY</h1>
          <p>Living intelligence — {agentCount} agents</p>
        </div>

        <div className="glass controls">
          <div className="seg">
            <button className={shownMode === 'explore' ? 'on' : ''} onClick={() => setMode('explore')}>
              Explore
            </button>
            <button
              className={shownMode === 'strategic' ? 'on' : ''}
              onClick={() => setMode('strategic')}
            >
              Strategic
            </button>
          </div>

          <div className="seg">
            <button
              className={dataSource === 'local' ? 'on' : ''}
              onClick={() => setDataSource('local')}
            >
              Live sim
            </button>
            <button
              className={dataSource === 'replay' ? 'on' : ''}
              onClick={() => setDataSource('replay')}
            >
              Replay{dataSource === 'replay' && !replayActive ? '…' : ''}
            </button>
          </div>

          <label className="field">
            <span>
              Population · <b style={{ color: 'var(--ink)' }}>{agentCount}</b>
            </span>
            <input
              type="range"
              min={100}
              max={2000}
              step={100}
              value={agentCount}
              onChange={(e) => setAgentCount(Number(e.target.value))}
            />
          </label>

          <div className="fps">{fps} FPS</div>
        </div>
      </div>

      <div className="glass legend">
        {ROLES.map((r) => (
          <div className="li" key={r}>
            <span className="dot" style={{ background: ROLE_HEX[r] }} />
            {ROLE_LABELS[r]}
          </div>
        ))}
        <div className="li">
          <span className="dot" style={{ background: PALETTE.verified }} />
          Verified lineage
        </div>
      </div>

      <div className="glass hint">
        {shownMode === 'explore' ? 'WASD move · mouse look · click to lock' : 'drag orbit · scroll zoom'}{' '}
        · V toggle view · click an ant
      </div>
    </div>
  )
}
