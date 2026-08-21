import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './api/client'
import type { Health, RecordsPage } from './api/client'
import { Inbox } from './routes/Inbox'
import { CheckLabel } from './routes/CheckLabel'
import { CheckBatch } from './routes/CheckBatch'
import { RecordDetail } from './routes/RecordDetail'
import { Export } from './routes/Export'
import { REVIEWER } from './lib/session'
import { ErrorBoundary } from './components/ErrorBoundary'

export function App() {

  const location = useLocation()

  // The same number the inbox leads with, not a second definition of
  // "outstanding" - and the counts alone, so one integer is not a whole store.
  const counts = useQuery({
    // Under the 'records' prefix, so any invalidation refreshes the badge too.
    queryKey: ['records', 'counts'],
    queryFn: () => api<RecordsPage>('/records?counts_only=true'),
    staleTime: 30_000,
  })
  const attention = counts.data?.counts.attention ?? 0

  // Verdict quality depends on which reader ran, so a degraded one is news.
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: 60_000,
  })
  const degraded =
    health.data != null &&
    (health.data.provider === 'fake' ||
      health.data.provider === 'ocr' ||
      health.data.reader_reachable === false)

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead-inner">
          <div className="brand">
            <div className="brand-mark">TTB</div>
            <div>
              <div className="brand-name">Label Verification Service</div>
              <div className="brand-sub">Certificate of Label Approval · Prototype</div>
            </div>
          </div>

          <nav className="nav" aria-label="Primary">
            <NavLink to="/inbox" className={({ isActive }) => (isActive ? 'active' : '')}>
              Review inbox
              {attention > 0 && <span className="nav-badge">{attention}</span>}
            </NavLink>
            <NavLink to="/check" className={({ isActive }) => (isActive ? 'active' : '')}>
              Check one label
            </NavLink>
            <NavLink to="/batch" className={({ isActive }) => (isActive ? 'active' : '')}>
              Batch upload
            </NavLink>
            <NavLink to="/export" className={({ isActive }) => (isActive ? 'active' : '')}>
              Records
            </NavLink>
          </nav>

          {/* Who determinations are recorded against, not a menu. */}
          <div className="agent">
            <div className="agent-avatar">{REVIEWER.initials}</div>
            <div>
              <div className="agent-name">{REVIEWER.name}</div>
              <div className="agent-role">{REVIEWER.role}</div>
            </div>
          </div>
        </div>
      </header>

      {degraded && (
        <div className="strip-warn" role="status">
          <strong>Verification is not using the vision reader.</strong>{' '}
          {health.data?.provider === 'openai'
            ? `The ${health.data.model} reader could not be initialised, so labels are read by local OCR.`
            : `READER_PROVIDER is set to ${health.data?.provider}, so labels are not read by a vision model.`}{' '}
          Accuracy is lower on blurred, angled and low-contrast captures.
        </div>
      )}

      <main>
        <ErrorBoundary key={location.pathname}>
        <Routes>
          <Route path="/" element={<Navigate to="/inbox" replace />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/check" element={<CheckLabel />} />
          <Route path="/batch" element={<CheckBatch />} />
          <Route path="/records/:id" element={<RecordDetail />} />
          <Route path="/export" element={<Export />} />
          {/* Older links kept working rather than 404ing. */}
          <Route path="/settings" element={<Navigate to="/export" replace />} />
          <Route path="/store" element={<Navigate to="/export" replace />} />
          {/* Anything else lands in the inbox rather than an empty page. */}
          <Route path="*" element={<Navigate to="/inbox" replace />} />
        </Routes>
        </ErrorBoundary>
      </main>
    </div>
  )
}
