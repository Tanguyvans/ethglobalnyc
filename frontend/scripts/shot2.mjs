import { chromium } from 'playwright'

const url = process.argv[2] || 'http://localhost:5173/'
const prefix = process.argv[3] || '/tmp/world'
const waitMs = Number(process.argv[4] || 5000)

const browser = await chromium.launch({
  args: ['--use-gl=angle', '--ignore-gpu-blocklist', '--enable-webgl'],
})
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 })

const errors = []
page.on('console', (m) => {
  if (m.type() === 'error' || m.type() === 'warning') errors.push(`[${m.type()}] ${m.text()}`)
})
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))

await page.goto(url, { waitUntil: 'domcontentloaded' }).catch((e) => errors.push(`[goto] ${e.message}`))
await page.waitForTimeout(waitMs)
await page.screenshot({ path: `${prefix}_overview.png` })

// toggle to the other camera mode (V) and re-shoot
await page.keyboard.press('v').catch(() => {})
await page.waitForTimeout(2500)
await page.screenshot({ path: `${prefix}_alt.png` })

console.log('--- errors/warnings (' + errors.length + ') ---')
console.log(errors.slice(0, 30).join('\n'))
console.log('--- saved ' + prefix + '_overview.png / _alt.png ---')
await browser.close()
