import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * Accessibility audit (PRD §10 M7). Serious and critical only: the lesser rules
 * are noisy on a dense table, and a suite that always fails is one nobody reads.
 */

const API = 'http://127.0.0.1:8031'

// Seed the store this suite audits rather than inheriting whatever ran before.
// review.spec.ts resets per test, so alone these specs passed and on a cold
// checkout they failed on an empty store - which is the one case the config
// promises works.
test.beforeAll(async ({ request }) => {
  const reset = await request.post(`${API}/api/fixtures`, {
    headers: {
      Authorization: `Bearer ${process.env.ADMIN_TOKEN ?? ''}`,
      'Content-Type': 'application/json',
    },
    data: { mode: 'reset' },
  })
  expect(reset.ok(), 'fixture reset must succeed or the audit has nothing to read').toBeTruthy()
})

async function auditFor(page: import('@playwright/test').Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  )
  // Name the rule and the element, so a failure is actionable as reported.
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
  // The densest page, and the id is resolved rather than hardcoded: a stale one
  // would redirect to the inbox and pass without auditing this page.
  const records = await (await request.get(`${API}/api/records`)).json()
  const id = records.records[0]?.id
  expect(id, 'seed the store before the a11y run').toBeTruthy()

  await page.goto(`/records/${id}`)
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
  await auditFor(page)
})
