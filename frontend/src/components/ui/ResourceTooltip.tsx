/**
 * ResourceTooltip — small floating label for the hovered resource crystal.
 * In-canvas <Html>; shows energy level + active workers. Reads sim.resources
 * directly at render (values drift slowly, so a near-live read is fine).
 */

import { Html } from '@react-three/drei'
import { useWorldStore } from '../../store/worldStore'
import { sim } from '../../store/simStore'

export default function ResourceTooltip() {
  const hovered = useWorldStore((s) => s.hoveredResource)
  if (hovered === null) return null
  const r = sim.resources[hovered]
  if (!r) return null

  return (
    <group position={[r.x, r.y + 7, r.z]}>
      <Html center distanceFactor={60} zIndexRange={[15, 0]} style={{ pointerEvents: 'none' }}>
        <div className="glass panel tooltip">
          <div className="panel-title" style={{ fontSize: 13, marginBottom: 8 }}>
            Resource node
          </div>
          <div className="row" style={{ marginBottom: 0 }}>
            <span className="k">Energy</span>
            <span className="v">{(r.energy * 100).toFixed(0)}%</span>
          </div>
          <div className="bar">
            <i style={{ width: `${r.energy * 100}%`, background: '#ffb84d' }} />
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <span className="k">Workers</span>
            <span className="v">{r.activeWorkers}</span>
          </div>
        </div>
      </Html>
    </group>
  )
}
