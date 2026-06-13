/**
 * HUD — screen-space DOM overlay (outside the Canvas): brand, camera + data
 * controls, population slider, legend, FPS, and key hints. Also owns the V/Tab
 * keyboard shortcut for the camera mode toggle.
 *
 * Camera switches go through beginTransition() so the rig lerps (never cuts).
 */

import { useEffect } from 'react'
import { useWorldStore, type CameraMode, type CameraTarget } from '../../store/worldStore'
import { COLONY_HEX } from '../../utils/palette'
import { sim } from '../../store/simStore'

const CASTES: [string, string][] = [
  ['#ffd23f', 'Queen'],
  ['#e8ff9c', 'Carrying food'],
  ['#ff5a4d', 'Soldier'],
]

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
      // 'V' toggles camera. Tab is intentionally NOT bound — it must stay free
      // for normal focus traversal / accessibility.
      if (e.code === 'KeyV') {
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
        {sim.colonies.map((_, i) => (
          <div className="li" key={i}>
            <span className="dot" style={{ background: COLONY_HEX[i % COLONY_HEX.length] }} />
            Colony {i + 1}
          </div>
        ))}
        {CASTES.map(([hex, label]) => (
          <div className="li" key={label}>
            <span className="dot" style={{ background: hex }} />
            {label}
          </div>
        ))}
      </div>

      <div className="glass hint">
        {shownMode === 'explore' ? 'WASD move · mouse look · click to lock' : 'drag orbit · scroll zoom'}{' '}
        · V toggle view · click an ant
      </div>
    </div>
  )
}
