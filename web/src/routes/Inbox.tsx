import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiUrl, imageUrl } from '../api/client'
import type { Job, RecordRow, RecordsPage, FieldResult, RecordDetail } from '../api/client'
import { Pill } from '../components/Pill'
import { DOT_COLOR, kindOf } from '../lib/verdict'
import { FIELD_LABEL, QUALITY_LABEL, engineLine } from '../lib/copy'

const FILTERS = [
  { key: 'attention', label: 'Needs attention' },
  { key: 'pending', label: 'Awaiting AI' },
  { key: 'review', label: 'Review' },
  { key: 'fail', label: 'Fail' },
  { key: 'closed', label: 'Closed' },
  { key: '', label: 'All' },
] as const

/** Search is case- and punctuation-insensitive (S5). */
const loosely = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '')

export function Inbox() {
  const [filter, setFilter] = useState<string>('attention')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const client = useQueryClient()

  const all = useQuery({
    queryKey: ['records', ''],
    queryFn: () => api<RecordsPage>('/records'),
  })
  const view = useQuery({
    queryKey: ['records', filter],
    queryFn: () => api<RecordsPage>(`/records${filter ? `?filter=${filter}` : ''}`),
  })

  const invalidate = () => client.invalidateQueries({ queryKey: ['records'] })

  const verify = useMutation({
    mutationFn: (id: string) => api(`/records/${id}/verify`, { method: 'POST' }),
    onMutate: (id: string) => setBusy(id),
    onSettled: () => {
      setBusy(null)
      invalidate()
    },
  })

  const verifyAll = useMutation({
    mutationFn: async () => {
      const job = await api<Job>('/jobs', {
        method: 'POST',
        body: { scope: 'pending', verify_now: true },
      })
      let state = job
      while (state.state === 'running') {
        await new Promise((r) => setTimeout(r, 350))
        state = await api<Job>(`/jobs/${job.id}`)
      }
      return state
    },
    onSuccess: invalidate,
  })

  const counts = all.data?.counts
  const total = all.data?.records.length ?? 0
  const closed = counts?.closed ?? 0
  const rows = (view.data?.records ?? []).filter((r) => {
    if (!query.trim()) return true
    const needle = loosely(query)
    return [r.id, r.applicant, r.app_brand, r.filename].some((v) =>
      loosely(v ?? '').includes(needle),
    )
  })

  const countFor = (key: string) =>
    key === '' ? total : (counts?.[key as keyof typeof counts] ?? 0)

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Queue</div>
          <h1>Review inbox</h1>
        </div>
        <div className="page-aside">
          {counts?.attention ?? 0} application{counts?.attention === 1 ? '' : 's'} require an
          agent; {closed} cleared automatically.
          <br />
          <span className="mono">{total} records persisted · records.csv</span>
        </div>
      </div>

      <div className="kpis">
        <button className="kpi kpi-pending" onClick={() => setFilter('pending')}>
          <div className="kpi-label">Awaiting AI check</div>
          <div className="kpi-value">{counts?.pending ?? 0}</div>
          <div className="kpi-hint">Uploaded, not yet verified</div>
        </button>
        <button className="kpi kpi-review" onClick={() => setFilter('review')}>
          <div className="kpi-label">Needs review</div>
          <div className="kpi-value">{counts?.review ?? 0}</div>
          <div className="kpi-hint">Formatting or unit differences</div>
        </button>
        <button className="kpi kpi-fail" onClick={() => setFilter('fail')}>
          <div className="kpi-label">Failed check</div>
          <div className="kpi-value">{counts?.fail ?? 0}</div>
          <div className="kpi-hint">Content differs or value missing</div>
        </button>
        <button className="kpi kpi-match" onClick={() => setFilter('closed')}>
          <div className="kpi-label">Auto-approved</div>
          <div className="kpi-value">{closed}</div>
          <div className="kpi-hint">All fields matched on intake</div>
        </button>
      </div>

      {(counts?.pending ?? 0) > 0 && (
        <div className="banner">
          <div className="banner-mark" aria-hidden="true">
            !
          </div>
          <div className="banner-text">
            {counts?.pending} uploaded application{counts?.pending === 1 ? ' has' : 's have'} not
            been checked. Run verification to extract label fields and compare them against the
            applications of record.
          </div>
          <button
            className="btn btn-gold push"
            onClick={() => verifyAll.mutate()}
            disabled={verifyAll.isPending}
          >
            {verifyAll.isPending && <span className="spinner spinner-dark" />}
            Run AI verification on all
          </button>
        </div>
      )}

      {verifyAll.data && (
        <div className="banner">
          <div className="banner-mark" aria-hidden="true">
            ✓
          </div>
          <div className="banner-text">
            Verified {verifyAll.data.completed} of {verifyAll.data.total} ·{' '}
            {Object.entries(verifyAll.data.verdicts)
              .map(([k, v]) => `${v} ${k}`)
              .join(' · ')}
            {verifyAll.data.failed > 0 && ` · ${verifyAll.data.failed} failed`}
          </div>
        </div>
      )}

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Filter records">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.label} <span className="count">{countFor(f.key)}</span>
            </button>
          ))}
        </div>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search brand, applicant, or COLA ID"
          aria-label="Search brand, applicant, or COLA ID"
          style={{ flex: 1, minWidth: 150 }}
        />
        <a className="btn btn-quiet" href={apiUrl('/export/records.csv')} download>
          Export CSV
        </a>
      </div>

      <div className="card">
        <div className="queue-head">
          <div />
          <div>Label</div>
          <div>Application</div>
          <div className="hide-sm">Applicant</div>
          <div className="hide-sm">Received</div>
          <div>Result</div>
          <div />
        </div>

        {rows.map((r) => (
          <QueueItem
            key={r.id}
            record={r}
            open={expanded === r.id}
            busy={busy === r.id}
            onToggle={() => setExpanded(expanded === r.id ? null : r.id)}
            onVerify={() => verify.mutate(r.id)}
          />
        ))}

        {view.isError && (
          <div className="empty">
            <div className="empty-title">Could not reach the API</div>
            <div className="empty-hint">Is the API running on port 8000?</div>
          </div>
        )}
        {!view.isLoading && !view.isError && rows.length === 0 && (
          <div className="empty">
            <div className="empty-title">Nothing in this view</div>
            <div className="empty-hint">
              Change the filter above, or load the bundled sample batch from Batch upload.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function QueueItem({
  record,
  open,
  busy,
  onToggle,
  onVerify,
}: {
  record: RecordRow
  open: boolean
  busy: boolean
  onToggle: () => void
  onVerify: () => void
}) {
  const kind = kindOf(record.result)
  const detail = useQuery({
    queryKey: ['record', record.id],
    queryFn: () => api<RecordDetail>(`/records/${record.id}`),
    enabled: open,
  })

  const subline = [
    record.id,
    record.filename,
    record.beverage,
    QUALITY_LABEL[record.quality ?? ''] ?? 'Clean capture',
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="queue-item">
      <button className="queue-row" onClick={onToggle} aria-expanded={open}>
        <div
          className="dot"
          style={{ background: record.decision ? '#c6d0da' : DOT_COLOR[kind] }}
        />
        <div className="thumb">
          <img src={imageUrl(record.specimen || record.filename)} alt="" />
        </div>
        <div style={{ minWidth: 0 }}>
          <div className="queue-brand">{record.app_brand}</div>
          <div className="queue-sub">{subline}</div>
        </div>
        <div className="queue-applicant hide-sm">{record.applicant}</div>
        <div className="queue-received hide-sm">{record.received.slice(0, 10)}</div>
        <div>
          {busy ? (
            <span className="pill pill-pending">Verifying…</span>
          ) : (
            <Pill verdict={record.result} />
          )}
          {record.decision && (
            <div style={{ fontSize: '10.5px', color: 'var(--ink-5)', marginTop: 4 }}>
              {record.decision === 'accepted' ? 'Accepted' : 'Returned'}
              {record.override ? ' · override' : ''}
            </div>
          )}
        </div>
        <div className={`caret${open ? ' open' : ''}`}>▾</div>
      </button>

      {open && (
        <div className="queue-expand">
          {record.verified ? (
            <div>
              <div className="fields-head fields-compact">
                <div>Item</div>
                <div>Application says</div>
                <div>Label shows</div>
                <div>Result</div>
              </div>
              {(detail.data?.field_results ?? []).map((f: FieldResult) => (
                <div className="fields-row fields-compact" key={f.field_key}>
                  <div className="fields-name" style={{ fontSize: 13, fontWeight: 600 }}>
                    {FIELD_LABEL[f.field_key] ?? f.field_key}
                  </div>
                  <div className="fields-value" style={{ fontSize: 13 }}>
                    {f.app_value || '—'}
                  </div>
                  <div className="fields-value" style={{ fontSize: 13 }}>
                    {f.label_value || 'Not on label'}
                  </div>
                  <div>
                    <Pill verdict={f.verdict} small />
                  </div>
                </div>
              ))}
              <div className="row" style={{ marginTop: 14 }}>
                <Link className="btn" to={`/records/${record.id}`}>
                  Open full determination
                </Link>
                <div className="push mono" style={{ fontSize: 11.5, color: 'var(--ink-6)' }}>
                  {engineLine(record)}
                </div>
              </div>
            </div>
          ) : (
            <div
              className="row"
              style={{
                padding: 16,
                background: '#fff',
                border: '1px solid #e0e6ed',
                borderRadius: 4,
              }}
            >
              <div style={{ fontSize: 13.5, color: 'var(--ink-3)', maxWidth: 560, lineHeight: 1.55 }}>
                This application has not been checked. Run verification to read the label
                specimen and compare every required field against the application of record.
              </div>
              <button className="btn push" onClick={onVerify} disabled={busy}>
                {busy && <span className="spinner" />}
                {busy ? 'Verifying…' : 'Run AI verification'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
