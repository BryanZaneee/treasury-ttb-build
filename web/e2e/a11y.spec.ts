import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * Accessibility audit (PRD §10 M7).
 *
 * Serious and critical violations only. The lesser rules produce a lot of
 * advisory noise on a dense data table, and a suite that always fails is one
 * nobody reads.
 */

const API = 'http://127.0.0.1:8031'

async function auditFor(page: import('@playwright/test').Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  )
  // Name the rule and the element, so a failure is actionable without
  // re-running with a reporter attached.
  const detail = serious
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
    .join('\n')
  expect(serious, detail).toEqual([])
}

const PAGES = [
  { name: 'inbox', path: '/inbox' },
  { name: 'single label', path: '/check' },
  { name: 'batch upload', path: '/batch' },
  { name: 'export', path: '/export' },
]

for (const { name, path } of PAGES) {
  test(`${name} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await auditFor(page)
  })
}

test('the determination has no serious accessibility violations', async ({ page, request }) => {
  // The densest page and the one a reviewer spends most time on, so the one
  // most worth auditing. The id is resolved rather than hardcoded: a stale id
  // would redirect to the inbox and the audit would pass without ever seeing
  // this page.
  const records = await (await request.get(`${API}/api/records`)).json()
  const id = records.records[0]?.id
  expect(id, 'seed the store before the a11y run').toBeTruthy()

  await page.goto(`/records/${id}`)
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
  await auditFor(page)
})
