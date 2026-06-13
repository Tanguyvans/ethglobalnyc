/** Crosshair — center reticle, shown only in explore (pointer-lock) mode. */

import { useWorldStore } from '../../store/worldStore'

export default function Crosshair() {
  const mode = useWorldStore((s) => s.cameraMode)
  if (mode !== 'explore') return null
  return <div className="crosshair" />
}
