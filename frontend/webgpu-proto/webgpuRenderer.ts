/**
 * R3F-8 + three r0.169 WebGPURenderer integration.
 *
 * THE KEY FACTS (verified against the installed node_modules):
 *
 * 1. R3F 8's `createRendererInstance` (events-*.esm.js) is SYNCHRONOUS:
 *        const customRenderer = typeof gl === 'function' ? gl(canvas) : gl;
 *        if (isRenderer(customRenderer)) return customRenderer;
 *    `isRenderer = def => !!(def != null && def.render)`.
 *    => The `gl` factory must SYNCHRONOUSLY return an object that already
 *       has a `.render` method. WebGPURenderer does, so R3F accepts it.
 *       R3F NEVER awaits the factory, so we cannot await `renderer.init()`
 *       inside it and still hand the renderer back in time.
 *
 * 2. Each frame R3F calls `state.gl.render(scene, camera)` synchronously.
 *    In r0.169, WebGPURenderer.render() before init does:
 *        console.warn('… .render() called before the backend is initialized…')
 *        return this.renderAsync(scene, camera)   // auto-inits
 *    => Calling sync .render() on an uninitialised WebGPURenderer is SAFE.
 *       The first frame(s) warn + kick off async init; once initialised,
 *       subsequent .render() calls take the normal synchronous path.
 *
 * Therefore the working pattern is: a sync factory that constructs the
 * WebGPURenderer, fires `renderer.init()` in the background (so we control
 * onInit / error reporting), and returns it immediately. R3F's render loop
 * then just works once init resolves.
 */
import { WebGPURenderer } from 'three/webgpu'
import * as THREE from 'three'

export type GLFactory = (canvas: HTMLCanvasElement) => THREE.Renderer

export interface WebGPUFactoryOpts {
  onInit?: (renderer: WebGPURenderer) => void
  onError?: (err: unknown) => void
  /** Force the WebGL2 fallback backend even if WebGPU is available. */
  forceWebGL?: boolean
}

/** Build the `gl={...}` factory to pass to R3F's <Canvas>. */
export function makeWebGPURenderer(opts: WebGPUFactoryOpts = {}): GLFactory {
  return (canvas: HTMLCanvasElement) => {
    const renderer = new WebGPURenderer({
      canvas,
      antialias: true,
      alpha: false,
      forceWebGL: opts.forceWebGL ?? false,
      // powerPreference is accepted by the backend descriptor
      powerPreference: 'high-performance',
    } as ConstructorParameters<typeof WebGPURenderer>[0])

    // Fire init in the background. We do NOT block the factory return.
    renderer
      .init()
      .then(() => opts.onInit?.(renderer))
      .catch((err) => opts.onError?.(err))

    // Returned synchronously; has `.render`, so R3F's isRenderer() passes.
    return renderer as unknown as THREE.Renderer
  }
}

/** Feature probe used by the UI to report environment support. */
export async function probeWebGPU(): Promise<{ ok: boolean; reason?: string }> {
  const nav = navigator as Navigator & { gpu?: unknown }
  if (!nav.gpu) return { ok: false, reason: 'navigator.gpu missing (no WebGPU)' }
  try {
    const adapter = await (nav.gpu as GPU).requestAdapter()
    if (!adapter) return { ok: false, reason: 'requestAdapter() returned null' }
    return { ok: true }
  } catch (e) {
    return { ok: false, reason: 'requestAdapter threw: ' + (e as Error).message }
  }
}
