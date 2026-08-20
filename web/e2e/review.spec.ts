import { expect, test } from '@playwright/test'

/**
 * The reviewer's path end to end (PRD §10 M7): work the inbox, verify, open the
 * determination, decide. These are the flows no unit test covers, because what
 * breaks them is routing, query invalidation and the proxy — not a function.
 *
 * The store is reset from the fixtures before each spec, so no spec inherits
 * another's decisions.
 */

const API = 'http://127.0.0.1:8031'

test.beforeEach(async ({ request }) => {
  const reset = await request.post(`${API}/api/fixtures`, {
    headers: {
      Authorization: `Bearer ${process.env.ADMIN_TOKEN ?? ''}`,
      'Content-Type': 'application/json',
    },
    data: { mode: 'reset' },
  })
  expect(reset.ok(), 'fixture reset must succeed or every spec is meaningless').toBeTruthy()
})

/** Verify what the example set left unchecked, and wait for the run to land. */
async function verifyAll(page: import('@playwright/test').Page) {
  await page.goto('/inbox')
  await page.getByRole('button', { name: 'Run AI verification on all' }).click()
  await page.getByRole('button', { name: 'Run verification' }).click()
  await expect(page.getByText(/applications filed|Verified/)).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText(/have not been checked/)).toBeHidden({ timeout: 120_000 })
}

test('the inbox opens on the example set, part-worked', async ({ page }) => {
  await page.goto('/inbox')
  await expect(page.getByRole('heading', { name: 'Review inbox' })).toBeVisible()
  // Three of the thirteen are still to check; the rest already carry a verdict.
  await expect(page.getByText(/3 uploaded applications have not been checked/)).toBeVisible()
  await expect(page.getByRole('button', { name: /^Fail/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Closed/ })).toBeVisible()
})

test('verifying the queue clears the unchecked banner', async ({ page }) => {
  await verifyAll(page)
  await expect(page.getByText(/have not been checked/)).toBeHidden()
})

test('a determination shows both sides and warns before overriding', async ({ page }) => {
  await verifyAll(page)
  await page.goto('/inbox?filter=fail')

  // Rows expand in place; the determination is a link inside the expanded row.
  await page.locator('.queue-main').first().click()
  await page.getByRole('link', { name: 'Open full determination' }).click()

  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
  await expect(page.getByText('Application says')).toBeVisible()
  await expect(page.getByText('Label shows')).toBeVisible()

  // Accepting a failure must name the disagreeing fields before it proceeds.
  await page.getByRole('button', { name: 'Accept determination' }).click()
  await expect(page.getByText('This record did not pass.')).toBeVisible()
  await expect(page.getByText(/overrides/i)).toBeVisible()
})

test('queue navigation walks the filter it came from', async ({ page }) => {
  await verifyAll(page)
  await page.goto('/inbox?filter=fail')
  await page.locator('.queue-main').first().click()
  await page.getByRole('link', { name: 'Open full determination' }).click()

  const nav = page.getByRole('navigation', { name: 'Queue navigation' })
  await expect(nav).toBeVisible()
  await expect(nav.getByText('Start of queue')).toBeVisible()

  const first = page.url()
  await nav.getByRole('link', { name: /Next/ }).click()
  await expect(page).not.toHaveURL(first)
  await expect(page).toHaveURL(/filter=fail/)
})

test('an unknown route lands in the inbox rather than a blank page', async ({ page }) => {
  await page.goto('/no-such-page')
  await expect(page.getByRole('heading', { name: 'Review inbox' })).toBeVisible()
})

test('a verified record survives leaving the page', async ({ page }) => {
  await verifyAll(page)
  await page.goto('/inbox?filter=fail')
  await page.locator('.queue-main').first().click()
  await page.getByRole('link', { name: 'Open full determination' }).click()
  const recordUrl = page.url()

  // Walk away mid-review, then come back.
  await page.goto('/export')
  await page.goto(recordUrl)
  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
  await expect(page.getByText('Application says')).toBeVisible()
})
