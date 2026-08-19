import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// PUBLIC_BASE_PATH threads into Vite `base` and the Router `basename`
// (PRD §9) so the app can be served under a subpath in production.
export default defineConfig(({ mode }) => {
  // .env lives at the repo root (shared with the API, per PRD §9), not in web/.
  const envDir = '..'
  const env = loadEnv(mode, envDir, '')
  const base = env.PUBLIC_BASE_PATH || '/'
  return {
    base,
    envDir,
    plugins: [react()],
    // Dev only: the production topology puts Caddy in front and routes /api to
    // the API container (PRD §9), so this proxy stands in for that locally.
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
