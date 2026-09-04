import { chromium } from 'playwright'

const url = process.argv[2] ?? 'http://localhost:5173/'
const outDir = process.argv[3] ?? '.'
const mode = process.argv[4] ?? 'initial' // 'initial' | 'running' | 'done'

const browser = await chromium.launch()

for (const scheme of ['light', 'dark']) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 }, colorScheme: scheme })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.waitForTimeout(300)

  if (mode === 'running' || mode === 'done') {
    await page.getByRole('button', { name: /run extraction/i }).click()
    if (mode === 'running') {
      await page.waitForTimeout(1400)
    } else {
      await page.waitForTimeout(6000)
    }
  }

  await page.screenshot({ path: `${outDir}/screenshot-${scheme}-${mode}.png`, fullPage: false })
  if (errors.length) {
    console.error(`[${scheme}] console errors:`, errors)
  } else {
    console.log(`[${scheme}] OK, no console errors`)
  }
  await page.close()
}

await browser.close()
