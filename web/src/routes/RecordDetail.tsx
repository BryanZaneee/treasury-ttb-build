import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, imageUrl } from '../api/client'
import type { Health, RecordDetail as Detail } from '../api/client'
import { Pill } from '../components/Pill'
import {
  FALLBACK_BODY,
  FALLBACK_TITLE,
  FIELD_LABEL,
  RESULT_COPY,
  contestedAccept,
  fieldValues,
  kindOf,
  readByFallback,
} from '../lib/copy'
import { REVIEWER } from '../lib/session'
import { QueueNav } from '../components/QueueNav'
import { Lightbox } from '../components/Lightbox'
import { useEscape } from '../lib/dialog'
import { useToast } from '../lib/toast'
import { readPanel, writePanel } from '../lib/review'

/**
 * The seven verified fields (PRD §3.1), tying each field key to its record column
 * and its PATCH key. The comparison table is driven by this rather than by the
 * field results, so an unverified or `invalid` record still has rows to type in.
 */
const FIELDS = [
  { key: 'brand', column: 'app_brand', app: 'brand' },
  { key: 'classType', column: 'app_class_type', app: 'class_type' },
  { key: 'abv', column: 'app_alcohol_content', app: 'abv' },
  { key: 'net', column: 'app_net_contents', app: 'net' },
  { key: 'producer', column: 'app_producer', app: 'producer' },
  { key: 'origin', column: 'app_origin', app: 'origin' },
  { key: 'warning', column: 'app_warning_declared', app: 'warning' },
] as const

type Draft = {
  brand: string
  class_type: string
  abv: string
  net: string
  producer: string
  origin: string
  warning: boolean
}

const draftFrom = (r: Detail): Draft => ({
  brand: r.app_brand,
  class_type: r.app_class_type,
  abv: r.app_alcohol_content,
  net: r.app_net_contents,
  producer: r.app_producer ?? '',
  origin: r.app_origin ?? '',
  warning: r.app_warning_declared,
})

/**
 * Previous and Next change the id without unmounting, which would carry a
 * half-typed correction onto the next record. The key makes each one a fresh page.
 */
export function RecordDetail() {
  const { id = '' } = useParams()
  return <Determination key={id} />
}

function Determination() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  // The queue the reviewer came from. An explicit empty filter is "All records";
  // no params at all is a deep link, which falls back to the inbox's default.
  const [params] = useSearchParams()
  const filter = params.has('filter') ? (params.get('filter') ?? '') : 'attention'
  const query = params.get('q') ?? ''
  const backToInbox = `/inbox${params.toString() ? `?${params}` : ''}`
  const client = useQueryClient()
  const [zoomed, setZoomed] = useState(false)
  // S10: `key={id}` remounts per record, so this reads the right id.
  const [minimised, setMinimised] = useState(() => readPanel(id))
  useEffect(() => writePanel({ recordId: id, minimised }), [id, minimised])
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<null | 'accepted' | 'returned'>(null)
  // Non-null while correcting in place: the reviewer types into the "Application
  // says" column itself, so there is no second copy of the seven fields.
  const [draft, setDraft] = useState<Draft | null>(null)
  useEscape(() => setZoomed(false))

  const toast = useToast()

  const record = useQuery({
    queryKey: ['record', id],
    queryFn: () => api<Detail>(`/records/${id}`),
  })

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: 60_000,
  })

  // Narrow on purpose: deciding a record drops it out of the `attention` filter,
  // so invalidating the whole prefix would delete the reviewer's own position and
  // dead-end Previous and Next. The inbox refetches on mount anyway.
  const refresh = () => {
    client.invalidateQueries({ queryKey: ['record', id] })
    client.invalidateQueries({ queryKey: ['records', 'counts'] })
  }

  const verify = useMutation({
    mutationFn: () => api<Detail>(`/records/${id}/verify`, { method: 'POST' }),
    onSuccess: (updated) => {
      if (readByFallback(updated, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
      refresh()
    },
    onError: (e) => toast({ kind: 'error', title: 'Verification failed', body: String(e) }),
  })

  // Adjudicated against the reading on file: the application changed, the label
  // did not, so no reader is asked to read the same image again.
  const save = useMutation({
    mutationFn: (draft: Draft) =>
      api<Detail>(`/records/${id}`, {
        method: 'PATCH',
        body: {
          application: {
            ...draft,
            producer: draft.producer || null,
            origin: draft.origin || null,
          },
        },
      }),
    onSuccess: (updated) => {
      setDraft(null)
      setError(null)
      refresh()
      toast({
        kind: 'success',
        title: 'Application corrected',
        body: updated.verified
          ? RESULT_COPY[kindOf(updated.result)]
          : 'Nothing has read this label yet. Run AI verification to compare it.',
      })
    },
    onError: (e) => toast({ kind: 'error', title: 'The correction was not saved', body: String(e) }),
  })

  const decide = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/records/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      setError(null)
      setConfirming(null)
      refresh()
    },
    onError: (err) => {
      if (err instanceof ApiError && typeof err.detail === 'object' && err.detail) {
        const detail = err.detail as { message?: string; fields?: string[] }
        setError(
          `${detail.message ?? 'Rejected.'} Disagreeing fields: ${(detail.fields ?? [])
            .map((f) => FIELD_LABEL[f] ?? f)
            .join(', ')}.`,
        )
      } else {
        setError(String(err))
      }
    },
  })

  const data = record.data
  if (record.isLoading) return <div className="empty">Loading…</div>
  if (record.isError)
    return <div className="banner-error">Could not load this record. {String(record.error)}</div>
  if (!data) return <div className="banner-error">Record not found.</div>

  const kind = kindOf(data.result)
  const disagreeing = data.field_results.filter((f) => f.verdict !== 'match')
  // Not from the field list: an `invalid` specimen writes no field rows, so
  // `disagreeing.length` would send override:false and be refused (PRD §3.2 ext).
  const needsOverride = data.result !== 'match'
  const closed = data.decision != null

  /**
   * Accept, challenging only when the challenge is worth making. PRD §5.1 still
   * records an override for anything short of a `match`; only a failed check or a
   * non-label earns the confirm step.
   */
  const acceptNow = () => {
    if (contestedAccept(data.result)) {
      setConfirming('accepted')
      return
    }
    decide.mutate({
      decision: 'accepted',
      override: needsOverride,
      reviewer_name: REVIEWER.name,
      reason: null,
    })
  }
  const busy = save.isPending || verify.isPending
  const results = new Map(data.field_results.map((f) => [f.field_key, f]))

  const startFixing = () => {
    setConfirming(null)
    setError(null)
    setDraft(draftFrom(data))
  }

  const verdictBlock = (
    <div className="result-verdict">
      <Pill verdict={data.result} />
      <div className="result-copy">{RESULT_COPY[kind]}</div>
    </div>
  )

  const header = (
    <QueueNav
      currentId={id}
      filter={filter}
      query={query}
      className={`result-head result-head-${kind} qn-c`}
    >
      {verdictBlock}
    </QueueNav>
  )

  /* Read from the record, not the field result, so a correction shows at once. */
  const current = draftFrom(data)
  const filed = (app: (typeof FIELDS)[number]['app']) =>
    app === 'warning' ? (current.warning ? 'Declared' : null) : current[app] || null

  const comparison = (
    <>
      <div className="fields-head">
        <div>Item</div>
        <div>Application says</div>
        <div>Label shows</div>
        <div>Result</div>
      </div>
      {FIELDS.map(({ key, app }) => {
        const result = results.get(key)
        return (
          <div className="fields-row" key={key}>
            <div>
              <div className="fields-name">{FIELD_LABEL[key]}</div>
              {result?.note && <div className="fields-note">{result.note}</div>}
            </div>
            <div className="fields-value fields-app">
              {draft ? (
                app === 'warning' ? (
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={draft.warning}
                      disabled={busy}
                      onChange={(e) => setDraft({ ...draft, warning: e.target.checked })}
                    />
                    <span>Declared on the application</span>
                  </label>
                ) : (
                  <input
                    type="text"
                    className="fields-edit"
                    value={draft[app]}
                    disabled={busy}
                    aria-label={`${FIELD_LABEL[key]} as filed`}
                    onChange={(e) => setDraft({ ...draft, [app]: e.target.value })}
                  />
                )
              ) : (
                filed(app) ?? <span className="fields-unrecorded">Not declared</span>
              )}
            </div>
            <div className="fields-value">
              {result ? (
                fieldValues(result).label
              ) : (
                /* Nothing read yet, or an optional field never declared and so
                   never adjudicated. */
                <span className="fields-unrecorded">
                  {data.verified ? 'Not compared' : 'Not read yet'}
                </span>
              )}
            </div>
            <div>{result && <Pill verdict={result.verdict} small />}</div>
          </div>
        )
      })}
    </>
  )

  return (
    <div>
      <button
        className="btn-link"
        style={{ marginBottom: 12 }}
        onClick={() => navigate(backToInbox)}
      >
        ← Back to review inbox
      </button>

      <div className="page-head">
        <div>
          <div className="eyebrow">Review findings</div>
          <h1>Application versus label</h1>
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <div className="card card-pad">
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
              <div className="card-title">Label image</div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }}>
                {data.filename}
              </div>
            </div>
            {/* A specimen is the evidence; 3:4 in a column is too small to read. */}
            <button
              type="button"
              className="label-frame label-frame-zoom"
              onClick={() => setZoomed(true)}
              aria-label={`Enlarge label image for ${data.app_brand}`}
            >
              <img
                src={imageUrl(data.specimen || data.filename)}
                alt={`Label image for ${data.app_brand}`}
              />
            </button>
            {readByFallback(data, health.data?.provider) && (
              <div className="row" style={{ gap: 8, marginTop: 12 }}>
                <span className="chip chip-warn">Read by local OCR</span>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          {header}

          {/* PRD §6.1 puts this on the decision bar, but a decided record has
              none - and that is exactly the case S10 describes. */}
          <div className="row" style={{ padding: '10px 14px 0', justifyContent: 'flex-end' }}>
            <button
              className="btn btn-quiet btn-sm"
              aria-expanded={!minimised}
              disabled={Boolean(draft)}
              onClick={() => setMinimised((v) => !v)}
            >
              {minimised ? 'Expand' : 'Minimise'}
            </button>
          </div>

          {minimised && !draft ? (
            /* The verdict header stays: a panel they cannot identify is not one
               they come back to. */
            <div className="empty">
              <div className="empty-title">Comparison minimised</div>
              <div className="empty-hint">
                {data.app_brand || data.filename} · {data.id}. Expand to read the field-by-field
                comparison again.
              </div>
            </div>
          ) : data.result === 'invalid' && !draft ? (
            /* Nothing was adjudicated (PRD §3.2 ext), so the table would be
               four column headers over nothing. */
            <div className="empty">
              <div className="empty-title">Nothing to compare</div>
              <div className="empty-hint">
                The reader found no alcohol beverage label in this image, so no field was
                adjudicated. Return the record and ask the applicant for the label artwork.
              </div>
            </div>
          ) : (
            comparison
          )}

          <div className="result-foot">
            {closed ? (
              /* Who decided it, and why. The flag and timestamp are recorded and
                 exported; a reviewer reading it back does not need them restated. */
              <div className="decided-note">
                {data.decision === 'accepted' ? 'Accepted' : 'Returned to applicant'} by{' '}
                {data.decided_by || 'unnamed reviewer'}
                {data.note && <div className="decided-reason">{data.note}</div>}
              </div>
            ) : draft ? (
              <div className="row">
                <button className="btn" disabled={busy} onClick={() => save.mutate(draft)}>
                  {save.isPending && <span className="spinner" />}
                  Save the correction
                </button>
                <button className="btn btn-quiet" disabled={busy} onClick={() => setDraft(null)}>
                  Cancel
                </button>
              </div>
            ) : confirming === null ? (
              /* Deciding is the job, so the decisions lead; an unverified record
                 has nothing to accept, so verification takes the front. */
              <div className="row">
                {data.verified ? (
                  <button
                    className="btn btn-accept"
                    disabled={decide.isPending}
                    onClick={() => acceptNow()}
                  >
                    {decide.isPending && <span className="spinner" />}
                    Accept
                  </button>
                ) : (
                  <button
                    className="btn"
                    onClick={() => verify.mutate()}
                    disabled={verify.isPending}
                  >
                    {verify.isPending && <span className="spinner" />}
                    Run AI verification
                  </button>
                )}
                <button className="btn btn-return" onClick={() => setConfirming('returned')}>
                  Return to applicant
                </button>
                <button className="btn btn-quiet" onClick={startFixing}>
                  Fix results
                </button>
                {data.verified && (
                  <button
                    className="btn btn-quiet"
                    onClick={() => verify.mutate()}
                    disabled={verify.isPending}
                  >
                    {verify.isPending && <span className="spinner" />}
                    Re-run AI verification
                  </button>
                )}
              </div>
            ) : (
              <div style={{ width: '100%' }}>
                {error && <div className="banner-error">{error}</div>}
                {confirming === 'accepted' && contestedAccept(data.result) && (
                  <div className="banner">
                    <div className="banner-mark" aria-hidden="true">
                      !
                    </div>
                    <div className="banner-text">
                      <strong>This record did not pass.</strong>{' '}
                      {disagreeing.length > 0 ? (
                        <>
                          Accepting it overrides {disagreeing.length} disagreeing field
                          {disagreeing.length === 1 ? '' : 's'}:{' '}
                          {disagreeing
                            .map((f) => FIELD_LABEL[f.field_key] ?? f.field_key)
                            .join(', ')}
                          .
                        </>
                      ) : (
                        <>
                          This image was not read as a label at all, so no field was compared.
                          Accepting it approves the application on your judgement alone.
                        </>
                      )}{' '}
                      Your name, the timestamp and the override flag are recorded.
                    </div>
                  </div>
                )}
                {confirming === 'returned' && (
                  <label className="field" style={{ maxWidth: 620 }}>
                    <span className="field-label">Reason returned to applicant</span>
                    <input
                      type="text"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </label>
                )}
                <p className="card-note">
                  This determination will be recorded against <strong>{REVIEWER.name}</strong>,
                  with the timestamp.
                </p>
                <div className="row">
                  <button
                    className={`btn ${confirming === 'accepted' ? 'btn-accept' : 'btn-return'}`}
                    disabled={decide.isPending}
                    onClick={() =>
                      decide.mutate({
                        decision: confirming,
                        override: confirming === 'accepted' && needsOverride,
                        reviewer_name: REVIEWER.name,
                        reason: confirming === 'returned' ? reason : null,
                      })
                    }
                  >
                    {decide.isPending && <span className="spinner" />}
                    Confirm {confirming === 'accepted' ? 'acceptance' : 'return'}
                  </button>
                  <button
                    className="btn btn-quiet"
                    onClick={() => {
                      setConfirming(null)
                      setError(null)
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {!data.verified && (
              <div
                className="push"
                style={{
                  fontSize: 12,
                  color: 'var(--ink-6)',
                  maxWidth: 360,
                  textAlign: 'right',
                  lineHeight: 1.5,
                }}
              >
                Nothing has been read yet. Run AI verification to compare this label against
                the application as filed.
              </div>
            )}
          </div>
        </div>
      </div>

      {zoomed && (
        <Lightbox
          src={imageUrl(data.specimen || data.filename)}
          alt={`Label image for ${data.app_brand}`}
          caption={data.filename}
          onClose={() => setZoomed(false)}
        />
      )}
    </div>
  )
}
