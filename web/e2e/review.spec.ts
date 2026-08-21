import { expect, test } from '@playwright/test'

/**
 * The reviewer's path end to end (PRD §10 M7): triage, verify, open, decide.
 * What breaks these is routing, cache invalidation and the proxy, not a
 * function. The store resets before each spec, so none inherits another's work.
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
  // Scoped to the filter strip: the KPI tiles name the same sets.
  const filters = page.getByRole('group', { name: 'Filter records' })
  await expect(filters.getByRole('button', { name: /^Fail/ })).toBeVisible()
  await expect(filters.getByRole('button', { name: /^Closed/ })).toBeVisible()
})

test('verifying the queue clears the unchecked banner', async ({ page }) => {
  await verifyAll(page)
  await expect(page.getByText(/have not been checked/)).toBeHidden()
})

test('a determination shows both sides and warns before overriding', async ({ page }) => {
  await verifyAll(page)
  await page.goto('/inbox?filter=fail')

  // Rows expand in place. The example set ships one already-returned failure,
  // and a decided record shows no decision bar, so pick an undecided one.
  const open = page
    .locator('.queue-item')
    .filter({ hasNotText: /Accepted|Returned/ })
    .first()
  await open.locator('.queue-main').click()
  await open.getByRole('link', { name: 'Review', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
  await expect(page.getByText('Application says')).toBeVisible()
  await expect(page.getByText('Label shows')).toBeVisible()

  // Accepting a failure must name the disagreeing fields before it proceeds.
  await page.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect(page.getByText('This record did not pass.')).toBeVisible()
  await expect(page.getByText(/overrides/i)).toBeVisible()
})

test('every row a run covers says it is verifying, from the click', async ({ page }) => {
  await page.goto('/inbox?filter=pending')
  const rows = page.locator('.queue-item')
  await expect(rows.first()).toBeVisible()
  const pending = await rows.count()

  // Hold POST /jobs open. The rows must already be marked before the server has
  // answered - the job cannot name its own record_ids until its worker thread
  // has started, and a cached reading can finish the whole run inside the first
  // poll interval.
  await page.route('**/api/jobs', async (route) => {
    await new Promise((r) => setTimeout(r, 3000))
    await route.continue()
  })

  await page.getByRole('button', { name: 'Run AI verification on all' }).click()
  await page.getByRole('button', { name: 'Run verification' }).click()

  await expect(page.getByText('Verifying…')).toHaveCount(pending)
  await page.unroute('**/api/jobs')
})

test('a needs-review record accepts in one click, a failure still challenges', async ({
  page,
}) => {
  await verifyAll(page)

  // A presentation difference is the ordinary thing a reviewer waves through,
  // so it files without a dialog.
  await page.goto('/inbox?filter=review')
  const row = page.locator('.queue-item').filter({ hasNotText: /Accepted|Returned/ }).first()
  await row.locator('.queue-main').click()
  await row.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/^Accepted$/).first()).toBeVisible()

  // A failed check still names the disagreeing fields before it is overridden.
  await page.goto('/inbox?filter=fail')
  const failing = page.locator('.queue-item').filter({ hasNotText: /Accepted|Returned/ }).first()
  await failing.locator('.queue-main').click()
  await failing.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText(/did not pass verification/)).toBeVisible()
})

test('the queue nav still steps after a decision', async ({ page }) => {
  await verifyAll(page)
  // The attention queue is the one that breaks, because it is `decision IS
  // NULL`. Pick a needs-review row inside it so the accept is the one-click
  // path and the test is about the nav, not about the dialog.
  await page.goto('/inbox?filter=attention')
  const row = page
    .locator('.queue-item')
    .filter({ hasText: 'Needs review' })
    .filter({ hasNotText: /Accepted|Returned/ })
    .first()
  await row.locator('.queue-main').click()
  await row.getByRole('link', { name: 'Review', exact: true }).click()

  // Deciding removes the record from the `attention` queue it was reviewed in.
  // The worklist must not be pulled out from under the reviewer standing on it.
  const next = page.getByRole('link', { name: /Next/ })
  await expect(next).toBeVisible()
  await page.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect(page.getByText(/^Accepted by/)).toBeVisible()
  await expect(next).toBeVisible()
  await next.click()
  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
})

test('queue navigation walks the filter it came from', async ({ page }) => {
  await verifyAll(page)
  await page.goto('/inbox?filter=fail')
  await page.locator('.queue-main').first().click()
  await page.getByRole('link', { name: 'Review', exact: true }).click()

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
  await page.getByRole('link', { name: 'Review', exact: true }).click()
  const recordUrl = page.url()

  // Walk away mid-review, then come back.
  await page.goto('/export')
  await page.goto(recordUrl)
  await expect(page.getByRole('heading', { name: 'Application versus label' })).toBeVisible()
  await expect(page.getByText('Application says')).toBeVisible()
})

test('a minimised determination is still minimised after a reload (S10)', async ({ page }) => {
  await verifyAll(page)
  await page.goto('/inbox?filter=fail')
  await page.locator('.queue-main').first().click()
  await page.getByRole('link', { name: 'Review', exact: true }).click()
  const recordUrl = page.url()

  await expect(page.getByText('Application says')).toBeVisible()
  await page.getByRole('button', { name: 'Minimise' }).click()
  await expect(page.getByText('Comparison minimised')).toBeVisible()
  await expect(page.getByText('Application says')).toHaveCount(0)

  // The collapsed state and the open record both survive the reload.
  await page.reload()
  await expect(page).toHaveURL(recordUrl)
  await expect(page.getByText('Comparison minimised')).toBeVisible()

  await page.getByRole('button', { name: 'Expand' }).click()
  await expect(page.getByText('Application says')).toBeVisible()
})

test('an open dialog keeps Tab inside it and gives focus back on close', async ({ page }) => {
  // `aria-modal="true"` tells assistive tech the page behind is inert, so a
  // dialog Tab can leave is misdescribing itself. axe cannot see focus
  // behaviour - it audits markup - so this is the check that covers it.
  await page.goto('/inbox')
  const opener = page.getByRole('button', { name: 'Run AI verification on all' })
  await opener.click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()

  // Focus starts inside, and ten tabs never take it out.
  await expect(dialog.locator(':focus')).toHaveCount(1)
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press('Tab')
    expect(
      await dialog.evaluate((el) => el.contains(document.activeElement)),
      `Tab ${i + 1} escaped the dialog`,
    ).toBe(true)
  }

  // Escape closes it and the opener gets focus back.
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(opener).toBeFocused()
})
