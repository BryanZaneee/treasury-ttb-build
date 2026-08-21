import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// PUBLIC_BASE_PATH threads into Vite `base` and the Router `basename` (PRD §9).
export default defineConfig(({ mode }) => {
  // .env lives at the repo root (shared with the API, per PRD §9), not in web/.
  const envDir = '..'
  const env = loadEnv(mode, envDir, '')
  // process.env wins, so a deploy can build for a subpath without editing .env.
  const base = process.env.PUBLIC_BASE_PATH || env.PUBLIC_BASE_PATH || '/'
  return {
    base,
    envDir,
    plugins: [react()],
    // Vitest's default glob would also collect the Playwright specs in e2e/.
    test: { include: ['src/**/*.{test,spec}.{ts,tsx}'] },
    // Dev only: Caddy does this in production (PRD §9).
    server: {
      proxy: {
        '/api': {
          target: env.DEV_API_URL || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
