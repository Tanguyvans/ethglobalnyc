// Headless WebGPU screenshot harness.
// Usage (from frontend/ root, with the vite dev server already running on :5180):
//   node webgpu-proto/screenshot.mjs
//
// Launches chromium with WebGPU enabled, waits for the proto to report it has
// initialised, then writes /tmp/webgpu_proto.png.
import { chromium } from 'playwright'

const URL = process.env.PROTO_URL || 'http://localhost:5180/'
const OUT = process.env.OUT || '/tmp/webgpu_proto.png'

const browser = await chromium.launch({
  headless: true,
  args: [
    '--enable-unsafe-webgpu',
    '--enable-features=Vulkan,WebGPU',
    '--use-angle=swiftshader', // software GPU so headless CI can run WebGPU/WebGL2
    '--use-gl=angle',
    '--ignore-gpu-blocklist',
    '--enable-gpu',
  ],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
const logs = []
page.on('console', (m) => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`))

await page.goto(URL, { waitUntil: 'networkidle' })

// Report adapter availability inside the page.
const gpu = await page.evaluate(async () => {
  const nav = navigator
  if (!nav.gpu) return { gpu: false }
  try {
    const a = await nav.gpu.requestAdapter()
    return { gpu: true, adapter: !!a }
  } catch (e) {
    return { gpu: true, adapter: false, err: String(e) }
  }
})
console.log('in-page gpu probe:', JSON.stringify(gpu))

// Wait up to 20s for the proto to flag init (or error).
let inited = false
for (let i = 0; i < 40; i++) {
  const st = await page.evaluate(() => ({
    inited: window.__WEBGPU_PROTO_INITED === true,
    backend: window.__WEBGPU_PROTO_BACKEND,
    error: window.__WEBGPU_PROTO_ERROR,
    status: window.__WEBGPU_PROTO_STATUS,
  }))
  if (st.inited) {
    console.log('proto initialised, backend =', st.backend)
    inited = true
    break
  }
  if (st.error) {
    console.log('proto error:', st.error)
    break
  }
  await page.waitForTimeout(500)
}
// let a few frames render
await page.waitForTimeout(1500)
await page.screenshot({ path: OUT })
console.log('screenshot ->', OUT, 'inited =', inited)
console.log('--- page console ---')
console.log(logs.slice(-40).join('\n'))
await browser.close()
