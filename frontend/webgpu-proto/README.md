# WebGPU + TSL vertical slice (R3F 8 / three r0.169)

Self-contained prototype proving a WebGPU rendering path for the colony app.
**Nothing under `frontend/` outside this folder is modified.** It reuses the
parent `frontend/node_modules` (three r0.169, R3F 8.18, react 18).

## Run

From the **`frontend/` root** (so node_modules resolves):

```bash
npx vite --config webgpu-proto/vite.config.ts
# open http://localhost:5180/
```

Headless screenshot (dev server must be running):

```bash
node webgpu-proto/screenshot.mjs        # writes /tmp/webgpu_proto.png
```

The screenshot harness launches chromium with
`--enable-unsafe-webgpu --enable-features=Vulkan,WebGPU --use-angle=swiftshader`.
WebGPU initialised with the **WebGPU backend** under headless swiftshader.

## What renders

TSL sky gradient + fog, TSL-displaced procedural terrain (mx_noise fbm height,
slope/altitude-blended albedo), animated TSL water plane, 400 role-tinted
instanced "ants", soft ambient+hemisphere+directional lighting (no black
shadows). All under `WebGPURenderer`.

## The R3F-8 + WebGPU integration pattern (verified)

R3F 8's `createRendererInstance` is **synchronous**:
`const r = typeof gl==='function' ? gl(canvas) : gl; if (r.render) return r;`.
It never awaits the factory. So the `gl` factory returns the WebGPURenderer
**synchronously** and inits it in the background:

```ts
import { WebGPURenderer } from 'three/webgpu'
gl={(canvas) => {
  const r = new WebGPURenderer({ canvas, antialias: true })
  r.init().then(onInit).catch(onError)   // background, NOT awaited
  return r                                // has .render => R3F accepts it
}}
```

Each frame R3F calls `state.gl.render(scene,camera)` synchronously. In r0.169,
`WebGPURenderer.render()` before init logs a warning and **auto-delegates to
`renderAsync()`** (which inits), so the first frames warn then it renders
normally. This is safe — no crash.

See `webgpuRenderer.ts` and `main.tsx`.

## Gotchas hit (all solved here)

- **Dual three instance.** R3F imports the WebGL `three` build; we import
  `three/webgpu` (a separate bundled copy of THREE). Console warns "Multiple
  instances of Three.js" — benign, but **lights/objects must come from the
  build the renderer understands.** R3F's JSX `<ambientLight/>` creates a
  WebGL-build light the node system ignores ("LightsNode: Light node not
  found" → unlit scene). Fix: construct lights from `three/webgpu` and mount
  via `<primitive>`. See `Scene.tsx`.
- **`time` is `timerLocal` in r0.169** (renamed to `time` in newer three).
  `timerLocal(scale)` is a *function* returning a node.
- **Instanced per-instance color:** `setColorAt`/`mesh.instanceColor` is NOT
  auto-wired into the node material. Bind a geometry
  `InstancedBufferAttribute('instanceColor', 3)` and read it in the material
  with `attribute('instanceColor','vec3')`.
- **Vertex displacement axis:** don't bake `geometry.rotateX`; keep the plane
  in local XY, displace `positionLocal.z`, rotate the *mesh* -90° X.
