/**
 * App — shell: the 3D Experience (Canvas) with the screen-space HUD + crosshair
 * layered on top as DOM siblings (outside the Canvas).
 */

import Experience from './components/Experience'
import HUD from './components/ui/HUD'
import Crosshair from './components/ui/Crosshair'
import './styles/ui.css'

export default function App() {
  return (
    <>
      <Experience />
      <HUD />
      <Crosshair />
    </>
  )
}
