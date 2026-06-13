/**
 * ColonyCard — floating spatial panel for the selected colony. In-canvas
 * <Html> anchored above the colony core; content from the throttled
 * colonySnapshot. One per type (only the selected colony).
 */

import { Html } from '@react-three/drei'
import { useWorldStore } from '../../store/worldStore'
import { sim } from '../../store/simStore'
import { terrainHeight } from '../../utils/noise'

export default function ColonyCard() {
  const selected = useWorldStore((s) => s.selectedColony)
  const snap = useWorldStore((s) => s.colonySnapshot)

  if (selected === null || !snap || snap.index !== selected) return null
  const c = sim.colonies[selected]
  if (!c) return null

  const pos: [number, number, number] = [c.x, terrainHeight(c.x, c.z) + 16, c.z]
  const verifiedPct = (snap.verifiedRatio * 100).toFixed(0)
  const anonPct = (100 - snap.verifiedRatio * 100).toFixed(0)

  return (
    <group position={pos}>
      <Html center distanceFactor={70} zIndexRange={[20, 0]} style={{ pointerEvents: 'none' }}>
        <div className="glass panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">Colony Core</div>
              <div className="panel-sub">{snap.population} agents</div>
            </div>
            <span className="badge gold">Live</span>
          </div>

          <div>
            <div className="row" style={{ marginBottom: 0 }}>
              <span className="k">Health</span>
              <span className="v">{(snap.health * 100).toFixed(0)}%</span>
            </div>
            <div className="bar">
              <i
                style={{
                  width: `${snap.health * 100}%`,
                  background: 'linear-gradient(90deg,#ffb84d,#ffd166)',
                }}
              />
            </div>
          </div>

          <div className="row" style={{ marginTop: 10 }}>
            <span className="k">Avg bankroll</span>
            <span className="v">${snap.bankroll.toFixed(1)}</span>
          </div>
          <div className="row">
            <span className="k">Avg accuracy</span>
            <span className="v">{(snap.accuracy * 100).toFixed(0)}%</span>
          </div>
          <div className="row">
            <span className="k">Growth</span>
            <span className="v">{(snap.growthRate * 100).toFixed(0)}%</span>
          </div>

          <div style={{ marginTop: 10 }}>
            <div className="row" style={{ marginBottom: 0 }}>
              <span className="k">Verified vs anon</span>
              <span className="v">
                {verifiedPct}% / {anonPct}%
              </span>
            </div>
            <div className="bar">
              <i
                style={{
                  width: `${snap.verifiedRatio * 100}%`,
                  background: 'linear-gradient(90deg,#ffe39a,#ffb84d)',
                }}
              />
            </div>
          </div>
        </div>
      </Html>
    </group>
  )
}
