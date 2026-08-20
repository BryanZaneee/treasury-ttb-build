import { readFileSync } from 'node:fs'

import { defineConfig, devices } from '@playwright/test'

// The tokens live in the root .env, which Vite loads for the browser bundle but
// Node does not load for this process. The specs need them to reset fixtures.
for (const line of readFileSync('../.env', 'utf8').split('\n')) {
  const [key, ...rest] = line.split('=')
  if (key && !key.startsWith('#') && rest.length) process.env[key.trim()] ??= rest.join('=').trim()
}

/**
 * End-to-end suite (PRD §10 M7).
 *
 * Runs against the fake reader so the whole thing is deterministic, free and
 * offline — the same reason CI uses it. Both servers are started here rather
 * than being assumed, so `npm run e2e` works from a cold checkout.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // one SQLite store, and the specs seed it
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5273',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command:
        'cd ../api && READER_PROVIDER=fake DATA_DIR=../data-e2e ' +
        'uv run uvicorn main:app --port 8031',
      url: 'http://127.0.0.1:8031/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // DEV_API_URL points the dev proxy at the e2e API rather than the
      // one a developer may already have running on 8000.
      command: 'DEV_API_URL=http://127.0.0.1:8031 npm run dev -- --port 5273 --strictPort',
      url: 'http://localhost:5273',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
})
