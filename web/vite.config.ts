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
  }
})
