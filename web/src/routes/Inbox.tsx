import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, freshUrl, imageUrl } from '../api/client'
import type { Job, RecordRow, RecordsPage, FieldResult, RecordDetail } from '../api/client'
import { Pill } from '../components/Pill'
import { DOT_COLOR, kindOf } from '../lib/verdict'
import { FIELD_LABEL, QUALITY_LABEL, engineLine, fieldValues } from '../lib/copy'
import { matchesQuery } from '../lib/search'
import { BulkDecisionDialog } from '../components/BulkDecisionDialog'
import { useToast } from '../lib/toast'
import { FALLBACK_BODY, FALLBACK_TITLE, readByFallback } from '../lib/fallback'
import { REVIEWER } from '../lib/session'

const FILTERS = [
  { key: 'attention', label: 'Needs attention' },
  { key: 'pending', label: 'Awaiting AI verification' },
  { key: 'review', label: 'Review' },
  { key: 'fail', label: 'Fail' },
  { key: 'closed', label: 'Closed' },
  { key: '', label: 'All' },
] as const

export function Inbox() {
  // Seeded from the URL so "Back to review inbox" returns to the queue the
  // reviewer left, rather than dropping them in the default view. Read once:
  // the inbox owns its filter after that, and rewriting the URL on every
  // keystroke would fill the history with search fragments.
  const [entry] = useSearchParams()
  const [filter, setFilterState] = useState<string>(
    () => entry.get('filter') ?? 'attention',
  )
  const [query, setQueryState] = useState(() => entry.get('q') ?? '')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  // Selection is scoped to what the reviewer can currently see. Changing the
  // filter or the search clears it, so a bulk action can never reach a record
  // that has scrolled out of the view they chose it from.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState<null | 'accepted' | 'returned'>(null)
  const client = useQueryClient()
  const toast = useToast()

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ provider: string }>('/health'),
    staleTime: 60_000,
  })

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
    mutationFn: (id: string) => api<RecordRow>(`/records/${id}/verify`, { method: 'POST' }),
    onMutate: (id: string) => setBusy(id),
    onSuccess: (record) => {
      if (readByFallback(record, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
    },
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
    onSuccess: async (job) => {
      invalidate()
      // One notice for the whole run, not one per record.
      const page = await api<RecordsPage>('/records')
      const degraded = page.records.filter((r) =>
        readByFallback(r, health.data?.provider),
      ).length
      if (degraded > 0) {
        toast({
          kind: 'warn',
          title: FALLBACK_TITLE,
          body: `${degraded} of ${job.completed} labels were read by local OCR because the vision reader was unavailable. ${FALLBACK_BODY}`,
        })
      }
    },
  })

  const bulkVerify = useMutation({
    mutationFn: async (ids: string[]) => {
      const started = await api<Job>('/jobs', {
        method: 'POST',
        body: { scope: 'ids', record_ids: ids, verify_now: true },
      })
      let state = started
      while (state.state === 'running') {
        await new Promise((r) => setTimeout(r, 350))
        state = await api<Job>(`/jobs/${started.id}`)
      }
      return state
    },
    onSuccess: (job) => {
      clearSelection()
      invalidate()
      toast({
        kind: 'info',
        title: `Verified ${job.completed} of ${job.total}`,
        body: Object.entries(job.verdicts)
          .map(([k, v]) => `${v} ${k}`)
          .join(' · '),
      })
    },
  })

  const bulkDecide = useMutation({
    mutationFn: async ({ decision, reason }: { decision: 'accepted' | 'returned'; reason: string }) => {
      let applied = 0
      let skipped = 0
      // One PATCH per record: the override rule is enforced per record server
      // side, and a record already decided answers 409 rather than reopening.
      for (const record of selectedRows) {
        try {
          await api(`/records/${record.id}`, {
            method: 'PATCH',
            body: {
              decision,
              override: decision === 'accepted' && record.result !== 'match',
              reviewer_name: REVIEWER.name,
              reason: decision === 'returned' ? reason || null : null,
            },
          })
          applied += 1
        } catch {
          skipped += 1
        }
      }
      return { applied, skipped, decision }
    },
    onSuccess: ({ applied, skipped, decision }) => {
      setConfirming(null)
      clearSelection()
      invalidate()
      toast({
        kind: skipped > 0 ? 'warn' : 'info',
        title: `${applied} ${decision === 'accepted' ? 'accepted' : 'returned'}`,
        body: skipped > 0 ? `${skipped} skipped — already closed, or rejected by the store.` : undefined,
      })
    },
  })

  const counts = all.data?.counts
  const total = all.data?.records.length ?? 0
  const closed = counts?.closed ?? 0
  const rows = (view.data?.records ?? []).filter((r) => matchesQuery(r, query))

  // Carried into the determination view so its worklist is this same queue.
  const queueParams = new URLSearchParams()
  queueParams.set('filter', filter)
  if (query) queueParams.set('q', query)
  const queueSearch = queueParams.toString() ? `?${queueParams}` : ''

  const visibleIds = rows.map((r) => r.id)
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id))
  const selectedRows = rows.filter((r) => selected.has(r.id))

  const clearSelection = () => setSelected(new Set())
  const setFilter = (next: string) => {
    clearSelection()
    setFilterState(next)
  }
  const setQuery = (next: string) => {
    clearSelection()
    setQueryState(next)
  }
  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(visibleIds))

  const countFor = (key: string) =>
    key === '' ? total : (counts?.[key as keyof typeof counts] ?? 0)

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Queue</div>
          <h1>Review inbox</h1>
        </div>
      </div>

      <div className="kpis">
        <button className="kpi kpi-pending" onClick={() => setFilter('pending')}>
          <div className="kpi-label">Awaiting AI verification</div>
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
        <a className="btn btn-quiet" href={freshUrl('/export/records.csv')} download>
          Export CSV
        </a>
      </div>

      <div className="card">
        {selected.size > 0 && (
          <div className="bulkbar">
            <span className="bulkbar-count">
              {selected.size} selected
            </span>
            <button
              className="btn btn-quiet btn-sm"
              onClick={() => bulkVerify.mutate([...selected])}
              disabled={bulkVerify.isPending}
            >
              {bulkVerify.isPending && <span className="spinner spinner-dark" />}
              Verify
            </button>
            <button
              className="btn btn-quiet btn-sm"
              onClick={() => setConfirming('accepted')}
              disabled={bulkVerify.isPending}
            >
              Accept
            </button>
            <button
              className="btn btn-quiet btn-sm"
              onClick={() => setConfirming('returned')}
              disabled={bulkVerify.isPending}
            >
              Return to applicant
            </button>
            <button className="btn btn-quiet btn-sm push" onClick={clearSelection}>
              Clear
            </button>
          </div>
        )}
        <div className="queue-head">
          <input
            type="checkbox"
            aria-label={allSelected ? 'Clear selection' : 'Select all visible records'}
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = selected.size > 0 && !allSelected
            }}
            onChange={toggleAll}
          />
          <div className="queue-head-main">
            <div />
            <div>Label</div>
            <div>Application</div>
            <div className="hide-sm">Applicant</div>
            <div className="hide-sm">Received</div>
            <div>Result</div>
            <div />
          </div>
        </div>

        {rows.map((r) => (
          <QueueItem
            key={r.id}
            record={r}
            open={expanded === r.id}
            busy={busy === r.id}
            onToggle={() => setExpanded(expanded === r.id ? null : r.id)}
            onVerify={() => verify.mutate(r.id)}
            queueSearch={queueSearch}
            checked={selected.has(r.id)}
            onSelect={() => toggleOne(r.id)}
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

      {confirming && (
        <BulkDecisionDialog
          decision={confirming}
          records={selectedRows}
          pending={bulkDecide.isPending}
          onCancel={() => setConfirming(null)}
          onConfirm={(reason) => bulkDecide.mutate({ decision: confirming, reason })}
        />
      )}
    </div>
  )
}

function QueueItem({
  record,
  open,
  busy,
  onToggle,
  onVerify,
  queueSearch,
  checked,
  onSelect,
}: {
  record: RecordRow
  open: boolean
  busy: boolean
  onToggle: () => void
  onVerify: () => void
  queueSearch: string
  checked: boolean
  onSelect: () => void
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
    <div className={`queue-item${checked ? ' selected' : ''}`}>
      <div className="queue-row">
        <input
          type="checkbox"
          checked={checked}
          aria-label={`Select ${record.app_brand}, ${record.id}`}
          onChange={onSelect}
        />
        <button className="queue-main" onClick={onToggle} aria-expanded={open}>
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
      </div>

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
                    {fieldValues(f).app}
                  </div>
                  <div className="fields-value" style={{ fontSize: 13 }}>
                    {fieldValues(f).label}
                  </div>
                  <div>
                    <Pill verdict={f.verdict} small />
                  </div>
                </div>
              ))}
              <div className="row" style={{ marginTop: 14 }}>
                <Link className="btn" to={`/records/${record.id}${queueSearch}`}>
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
