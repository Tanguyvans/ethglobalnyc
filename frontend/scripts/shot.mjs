import { chromium } from 'playwright'

const url = process.argv[2] || 'http://localhost:5173/'
const out = process.argv[3] || '/tmp/colony.png'
const waitMs = Number(process.argv[4] || 3500)

const browser = await chromium.launch({ args: ['--use-gl=angle', '--ignore-gpu-blocklist', '--enable-webgl'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })

const logs = []
page.on('console', (m) => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`))

await page.goto(url, { waitUntil: 'networkidle' }).catch((e) => logs.push(`[goto] ${e.message}`))
await page.waitForTimeout(waitMs)
await page.screenshot({ path: out })

console.log('--- console (' + logs.length + ') ---')
console.log(logs.slice(0, 40).join('\n'))
console.log('--- saved ' + out + ' ---')
await browser.close()
