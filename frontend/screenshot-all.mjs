import { chromium } from 'playwright'

const url = 'http://localhost:5173/'
const browser = await chromium.launch()

const steps = [
  { id: 'extraction', label: 'Extraction' },
  { id: 'surface', label: 'Surface' },
  { id: 'agent', label: 'Agent mode' },
  { id: 'results', label: 'Results' },
]

for (const scheme of ['light', 'dark']) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 }, colorScheme: scheme })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.waitForTimeout(300)

  // extraction: run it and let it finish
  await page.getByRole('button', { name: /run extraction/i }).click()
  await page.waitForTimeout(6000)
  await page.screenshot({ path: `screenshot-${scheme}-1-extraction.png` })

  for (const step of steps.slice(1)) {
    await page.getByRole('button', { name: step.label, exact: false }).first().click()
    await page.waitForTimeout(300)
    if (step.id === 'agent') {
      await page.getByRole('button', { name: /run session/i }).click()
      await page.waitForTimeout(9000)
    }
    await page.screenshot({ path: `screenshot-${scheme}-${steps.indexOf(step) + 1}-${step.id}.png` })
  }

  if (errors.length) {
    console.error(`[${scheme}] console errors:`, errors)
  } else {
    console.log(`[${scheme}] OK, no console errors`)
  }
  await page.close()
}

await browser.close()
