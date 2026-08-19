import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import { App } from './App.tsx'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* import.meta.env.BASE_URL mirrors Vite `base`, itself driven by
          PUBLIC_BASE_PATH (PRD §9) — the two must agree, so this reads the
          same value rather than a second env lookup.

          Vite's `base` requires the trailing slash; React Router's `basename`
          must not have one. With it, the router strips a character too many and
          every deep link resolves to a path with no leading slash, which
          matches the wrong route. */}
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
