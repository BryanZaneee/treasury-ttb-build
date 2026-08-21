import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, freshUrl, imageUrl } from '../api/client'
import type { Job, RecordRow, RecordsPage, FieldResult, RecordDetail } from '../api/client'
import { Pill } from '../components/Pill'
import {
  DOT_COLOR,
  FALLBACK_BODY,
  FALLBACK_TITLE,
  FIELD_LABEL,
  QUALITY_LABEL,
  contestedAccept,
  fieldValues,
  kindOf,
  readByFallback,
  verdictSummary,
} from '../lib/copy'
import { matchesQuery } from '../lib/search'
import { BulkDecisionDialog } from '../components/BulkDecisionDialog'
import { Lightbox } from '../components/Lightbox'
import { Dialog } from '../components/Dialog'
import { useEscape } from '../lib/dialog'
import { useToast } from '../lib/toast'
import { REVIEWER } from '../lib/session'
import { waitForJob } from '../lib/job'

const FILTERS = [
  { key: 'attention', label: 'Needs attention' },
  { key: 'pending', label: 'Awaiting AI verification' },
  { key: 'review', label: 'Review' },
  { key: 'fail', label: 'Fail' },
  { key: 'closed', label: 'Closed' },
  { key: '', label: 'All' },
] as const

/** What a run produced, as a sentence. */
function verdictReport(job: Job): string {
  const verdicts = verdictSummary(job.verdicts)
  if (job.failed === 0) return verdicts
  const unread = `${job.failed} could not be read`
  return verdicts ? `${verdicts}. ${unread}.` : `${unread}.`
}

export function Inbox() {
  // Seeded from the URL so "Back to review inbox" returns to the queue the
  // reviewer left. Read once: rewriting it per keystroke would fill the history.
  const [entry] = useSearchParams()
  const [filter, setFilterState] = useState<string>(
    () => entry.get('filter') ?? 'attention',
  )
  const [query, setQueryState] = useState(() => entry.get('q') ?? '')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set())
  // Polled, so the page moves during a run rather than showing one spinner.
  const [job, setJob] = useState<Job | null>(null)
  const seen = useRef(0)
  const [exporting, setExporting] = useState(false)
  const [verifyingAll, setVerifyingAll] = useState(false)
  // Scoped to what is on screen: changing the filter or search clears it, so a
  // bulk action cannot reach a record the reviewer never saw.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Carries its own records: the same dialog confirms a bulk action and a single
  // row, and that row is not in `selected`.
  const [confirming, setConfirming] = useState<
    null | { decision: 'accepted' | 'returned'; records: RecordRow[] }
  >(null)
  const client = useQueryClient()
  const toast = useToast()
  useEscape(() => {
    setExporting(false)
    setVerifyingAll(false)
    setConfirming(null)
  })

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ provider: string }>('/health'),
    staleTime: 60_000,
  })

  const view = useQuery({
    queryKey: ['records', filter],
    queryFn: () => api<RecordsPage>(`/records${filter ? `?filter=${filter}` : ''}`),
  })

  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ['records'] })
    // Separate key, so the prefix above misses it: an expanded row would keep
    // rendering the field results it cached while the record was unverified.
    void client.invalidateQueries({ queryKey: ['record'] })
  }

  const verify = useMutation({
    mutationFn: (id: string) => api<RecordRow>(`/records/${id}/verify`, { method: 'POST' }),
    onMutate: (id: string) => setBusy((prev) => new Set(prev).add(id)),
    onSuccess: (record) => {
      if (readByFallback(record, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
    },
    onError: (e) => toast({ kind: 'error', title: 'Verification failed', body: String(e) }),
    onSettled: (_record, _error, id) => {
      setBusy((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      invalidate()
    },
  })

  /**
   * Start a job and follow it, so every row it covers says so while it waits.
   *
   * `targets` are marked busy before the request is sent: POST /jobs answers
   * before the worker has filled in `record_ids`, and a cached reading can
   * finish the run inside the first poll. Events then release rows one by one.
   */
  const followJob = async (body: Record<string, unknown>, targets: string[]) => {
    seen.current = 0
    setBusy((prev) => new Set([...prev, ...targets]))
    const release = (ids: Iterable<string>) =>
      setBusy((prev) => {
        const next = new Set(prev)
        for (const id of ids) next.delete(id)
        return next
      })
    try {
      const started = await api<Job>('/jobs', { method: 'POST', body })
      return await waitForJob(started, (tick) => {
        setJob(tick)
        const done = tick.events.flatMap((e) => (e.record_id ? [e.record_id] : []))
        // Refetch on progress, not on every 350ms poll: this is what turns a
        // row from "Verifying…" into its verdict while the run is still going.
        if (done.length !== seen.current) {
          seen.current = done.length
          release(done)
          invalidate()
        }
      })
    } finally {
      setJob(null)
      release(targets)
    }
  }

  const verifyAll = useMutation({
    // Only rows on screen need to say they are working; the server derives its
    // own set, so a tab listing none is right rather than missing something.
    mutationFn: () =>
      followJob(
        { scope: 'pending', verify_now: true },
        (view.data?.records ?? []).filter((r) => !r.verified).map((r) => r.id),
      ),
    onSuccess: async (job) => {
      invalidate()
      toast({
        kind: job.failed > 0 ? 'warn' : 'success',
        title: `Verified ${job.completed} of ${job.total}`,
        body: verdictReport(job),
      })
      // One notice per run. The run already succeeded, so a failed follow-up
      // must not reject out of onSuccess.
      try {
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
      } catch {
        /* the verdicts landed; the advisory is best-effort */
      }
    },
    onError: (e) => toast({ kind: 'error', title: 'Verification failed', body: String(e) }),
  })

  const bulkVerify = useMutation({
    mutationFn: (ids: string[]) =>
      followJob({ scope: 'ids', record_ids: ids, verify_now: true }, ids),
    onSuccess: (job) => {
      clearSelection()
      invalidate()
      toast({
        kind: job.completed < job.total ? 'warn' : 'success',
        title: `Verified ${job.completed} of ${job.total}`,
        body: verdictReport(job),
      })
    },
    onError: (e) => toast({ kind: 'error', title: 'Verification failed', body: String(e) }),
  })

  const bulkDecide = useMutation({
    mutationFn: async ({
      decision,
      reason,
      records,
    }: {
      decision: 'accepted' | 'returned'
      reason: string
      records: RecordRow[]
    }) => {
      let applied = 0
      let skipped = 0
      // A record the store refuses (409 already closed, 422 override) is
      // skipped; anything else - 401, 429, a dropped connection - is a real
      // failure and must not be reported to the reviewer as "already closed".
      let failed = 0
      // One PATCH per record: the override rule is enforced per record, and an
      // already-decided one answers 409 rather than reopening.
      for (const record of records) {
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
        } catch (e) {
          if (e instanceof ApiError && (e.status === 409 || e.status === 422)) skipped += 1
          else failed += 1
        }
      }
      return { applied, skipped, failed, decision }
    },
    onSuccess: ({ applied, skipped, failed, decision }) => {
      setConfirming(null)
      clearSelection()
      invalidate()
      const notes = [
        skipped > 0 ? `${skipped} skipped: already closed, or rejected by the store.` : '',
        failed > 0 ? `${failed} could not be recorded — check the connection and retry.` : '',
      ].filter(Boolean)
      toast({
        kind: failed > 0 ? 'error' : skipped > 0 ? 'warn' : 'success',
        title: `${applied} ${decision === 'accepted' ? 'accepted' : 'returned'}`,
        body: notes.join(' ') || undefined,
      })
    },
    onError: (e) =>
      toast({ kind: 'error', title: 'Nothing was recorded', body: String(e) }),
  })

  /**
   * Confirm only where confirmation earns its place. PRD §5.1's override is still
   * recorded for anything short of a `match`; what is narrower is the interruption
   * — a `review` verdict is the ordinary thing a reviewer waves through.
   */
  const decideOn = (decision: 'accepted' | 'returned', records: RecordRow[]) => {
    if (decision === 'accepted' && !records.some((r) => contestedAccept(r.result))) {
      bulkDecide.mutate({ decision, reason: '', records })
      return
    }
    setConfirming({ decision, records })
  }

  // Whole-store whatever the filter, so no second fetch just for the counts.
  const counts = view.data?.counts
  const total = counts?.total ?? 0
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
          <div className="kpi-label">Closed</div>
          <div className="kpi-value">{closed}</div>
          <div className="kpi-hint">Accepted or returned by a reviewer</div>
        </button>
      </div>

      <div className="sr-only" role="status" aria-live="polite">
        {job && job.state === 'running' ? `Verified ${job.completed} of ${job.total}` : ''}
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
            onClick={() => setVerifyingAll(true)}
            disabled={verifyAll.isPending}
          >
            {verifyAll.isPending && <span className="spinner spinner-dark" />}
            {/* Reassurance on a slow run; announced too (PRD §8). */}
            {verifyAll.isPending && job
              ? `Verifying ${job.completed} of ${job.total}…`
              : 'Run AI verification on all'}
          </button>
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
        <button className="btn btn-quiet" onClick={() => setExporting(true)}>
          Export CSV
        </button>
      </div>

      <div className="card">
        {/* Replaces the header rather than sitting above it, so ticking a box
            does not push the table down. */}
        {selected.size > 0 ? (
          <div className="bulkbar">
            <span className="bulkbar-check">
              <input
                type="checkbox"
                aria-label={allSelected ? 'Clear selection' : 'Select all visible records'}
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = selected.size > 0 && !allSelected
                }}
                onChange={toggleAll}
              />
            </span>
            <span className="bulkbar-count">{selected.size} selected</span>
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
              onClick={() => decideOn('accepted', selectedRows)}
              disabled={bulkVerify.isPending || bulkDecide.isPending}
            >
              Accept
            </button>
            <button
              className="btn btn-quiet btn-sm"
              onClick={() => decideOn('returned', selectedRows)}
              disabled={bulkVerify.isPending || bulkDecide.isPending}
            >
              Return to applicant
            </button>
            <button className="btn btn-quiet btn-sm push" onClick={clearSelection}>
              Clear
            </button>
          </div>
        ) : (
          <div className="queue-head">
            <input
              type="checkbox"
              aria-label="Select all visible records"
              checked={false}
              onChange={toggleAll}
            />
            <div />
            <div>Label</div>
            <div className="queue-head-main">
              <div>Application</div>
              <div className="hide-sm">Received</div>
              <div>Result</div>
              <div />
            </div>
          </div>
        )}

        {rows.map((r) => (
          <QueueItem
            key={r.id}
            record={r}
            open={expanded === r.id}
            busy={busy.has(r.id)}
            onToggle={() => setExpanded(expanded === r.id ? null : r.id)}
            onVerify={() => verify.mutate(r.id)}
            queueSearch={queueSearch}
            checked={selected.has(r.id)}
            onSelect={() => toggleOne(r.id)}
            onDecide={(decision) => decideOn(decision, [r])}
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

      {/* A paid call per record, so a whole-queue run says how many first. */}
      {verifyingAll && (
        <Dialog
          title={`Verify ${counts?.pending} application${counts?.pending === 1 ? '' : 's'}?`}
          titleId="verify-all-title"
          onClose={() => setVerifyingAll(false)}
          footer={
            <>
              <button
                className="btn"
                onClick={() => {
                  setVerifyingAll(false)
                  verifyAll.mutate()
                }}
              >
                Run verification
              </button>
              <button className="btn btn-quiet" onClick={() => setVerifyingAll(false)}>
                Cancel
              </button>
            </>
          }
        >
          <p className="card-note">
            The AI reads each label and every field is checked against the application as filed.
            Applications already verified are left alone, and a label that cannot be read stays
            unverified rather than stopping the run.
          </p>
        </Dialog>
      )}

      {exporting && (
        <Dialog
          title="Export the review inbox"
          titleId="export-title"
          onClose={() => setExporting(false)}
          footer={
            <>
              <a
                className="btn"
                href={freshUrl('/export/records.csv')}
                download
                onClick={() => setExporting(false)}
              >
                Download CSV
              </a>
              <button className="btn btn-quiet" onClick={() => setExporting(false)}>
                Cancel
              </button>
            </>
          }
        >
          <p className="card-note">
            Downloads every application in the store as it stands right now: all {total}, not only
            the {rows.length} this filter is showing. Each row carries the application as filed,
            the result, any fields that did not match, and the decision.
          </p>
        </Dialog>
      )}

      {confirming && (
        <BulkDecisionDialog
          decision={confirming.decision}
          records={confirming.records}
          pending={bulkDecide.isPending}
          onCancel={() => setConfirming(null)}
          onConfirm={(reason) =>
            bulkDecide.mutate({ decision: confirming.decision, reason, records: confirming.records })
          }
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
  onDecide,
}: {
  record: RecordRow
  open: boolean
  busy: boolean
  onToggle: () => void
  onVerify: () => void
  queueSearch: string
  checked: boolean
  onSelect: () => void
  onDecide: (decision: 'accepted' | 'returned') => void
}) {
  const kind = kindOf(record.result)
  const [zoomed, setZoomed] = useState(false)
  useEscape(() => setZoomed(false))
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
        <div
          className="dot"
          style={{ background: record.decision ? '#c6d0da' : DOT_COLOR[kind] }}
        />
        {/* Outside the row button: buttons cannot nest, and this opens the image. */}
        <button
          className="thumb"
          onClick={() => setZoomed(true)}
          aria-label={`Enlarge label image for ${record.app_brand}`}
        >
          <img src={imageUrl(record.specimen || record.filename)} alt="" />
        </button>
        <button className="queue-main" onClick={onToggle} aria-expanded={open}>
        <div style={{ minWidth: 0 }}>
          <div className="queue-brand">{record.app_brand}</div>
          <div className="queue-sub">{subline}</div>
        </div>
        <div className="queue-received hide-sm">{record.received.slice(0, 10)}</div>
        <div>
          {busy ? (
            <span className="pill pill-pending">Verifying…</span>
          ) : (
            <Pill verdict={record.result} />
          )}
          {record.decision && (
            <div className="queue-decided">
              {record.decision === 'accepted' ? 'Accepted' : 'Returned'}
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
              {(detail.data?.field_results ?? []).map((f: FieldResult) => {
                const values = fieldValues(f)
                const valueClass = `fields-value${values.recorded ? '' : ' fields-unrecorded'}`
                return (
                <div className="fields-row fields-compact" key={f.field_key}>
                  <div className="fields-name" style={{ fontSize: 13, fontWeight: 600 }}>
                    {FIELD_LABEL[f.field_key] ?? f.field_key}
                  </div>
                  <div className={valueClass} style={{ fontSize: 13 }}>
                    {values.app}
                  </div>
                  <div className={valueClass} style={{ fontSize: 13 }}>
                    {values.label}
                  </div>
                  <div>
                    <Pill verdict={f.verdict} small />
                  </div>
                </div>
                )
              })}
              <div className="row" style={{ marginTop: 14 }}>
                <Link className="btn" to={`/records/${record.id}${queueSearch}`}>
                  Review
                </Link>
                {/* The shared dialog names the disagreeing fields first. */}
                {!record.decision && (
                  <>
                    <button className="btn btn-accept" onClick={() => onDecide('accepted')}>
                      Accept
                    </button>
                    <button className="btn btn-return" onClick={() => onDecide('returned')}>
                      Return to applicant
                    </button>
                  </>
                )}
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
                image and compare every required field against the application of record.
              </div>
              <button className="btn push" onClick={onVerify} disabled={busy}>
                {busy && <span className="spinner" />}
                {busy ? 'Verifying…' : 'Run AI verification'}
              </button>
            </div>
          )}
        </div>
      )}

      {zoomed && (
        <Lightbox
          src={imageUrl(record.specimen || record.filename)}
          alt={`Label image for ${record.app_brand}`}
          caption={record.filename}
          onClose={() => setZoomed(false)}
        />
      )}
    </div>
  )
}
