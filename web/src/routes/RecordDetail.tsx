import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, imageUrl } from '../api/client'
import type { Health, RecordDetail as Detail } from '../api/client'
import { Pill } from '../components/Pill'
import { contestedAccept, kindOf } from '../lib/verdict'
import { FIELD_LABEL, RESULT_COPY, fieldValues } from '../lib/copy'
import { REVIEWER } from '../lib/session'
import { QueueNav } from '../components/QueueNav'
import { useEscape } from '../lib/dialog'
import { useToast } from '../lib/toast'
import { FALLBACK_BODY, FALLBACK_TITLE, readByFallback } from '../lib/fallback'

/**
 * The seven verified fields (PRD §3.1), each tying the adjudicated field key to
 * the record column it was filed in and the key a PATCH sends it back under.
 *
 * The comparison table is driven by this list rather than by the field results,
 * so every field has a row to type in: a record that has never been verified,
 * or one read as `invalid`, has no field rows at all (PRD §3.2 extension).
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
 * half-typed correction - and the confirmation state under it - onto the next
 * record. Keying on the id makes stepping through the queue a fresh page.
 */
export function RecordDetail() {
  const { id = '' } = useParams()
  return <Determination key={id} />
}

function Determination() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  // The queue the reviewer came from. Deep-linking straight to a record with no
  // params falls back to the inbox's own default view.
  const [params] = useSearchParams()
  // An explicit empty filter is the "All records" queue, which is different
  // from arriving with no params at all - that is a deep link, and the inbox's
  // own default view is the sensible queue for it.
  const filter = params.has('filter') ? (params.get('filter') ?? '') : 'attention'
  const query = params.get('q') ?? ''
  const backToInbox = `/inbox${params.toString() ? `?${params}` : ''}`
  const client = useQueryClient()
  const [zoomed, setZoomed] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<null | 'accepted' | 'returned'>(null)
  // Non-null while the application is being corrected in place. The reviewer
  // types into the "Application says" column itself, so there is no separate
  // form and no second copy of the seven fields to keep in step.
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

  const refresh = () => {
    client.invalidateQueries({ queryKey: ['record', id] })
    client.invalidateQueries({ queryKey: ['records'] })
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

  // The correction is only ever adjudicated against the reading already on
  // file: the application changed, the label did not, so the API re-runs the
  // rules and never asks a reader to read the same image again.
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
  if (!data) return <div className="banner-error">Record not found.</div>

  const kind = kindOf(data.result)
  const disagreeing = data.field_results.filter((f) => f.verdict !== 'match')
  // Not derived from the field list: an `invalid` specimen is adjudicated as a
  // whole and writes no field rows at all (PRD §3.2 extension), so a flag taken
  // from `disagreeing.length` would send override:false and be refused by the
  // store with an empty list of fields to explain why.
  const needsOverride = data.result !== 'match'
  const closed = data.decision != null
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

  /* The application as filed, for the "Application says" column. Read from the
     record rather than from the field result, so a correction shows the moment
     it is saved even though adjudication cleared the field rows. */
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
                /* No field row: either nothing has been read yet, or this
                   optional field was left undeclared and so was never
                   adjudicated against the label. */
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
            {/* Same click-to-enlarge as the staged batch preview: a specimen
                is the evidence, and 3:4 in a column is too small to read. */}
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

          {data.result === 'invalid' && !draft ? (
            /* No fields were adjudicated (PRD §3.2 ext), so the comparison
               table would be four column headers over nothing. */
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
              <div
                style={{
                  fontSize: 13.5,
                  color: 'var(--ink-3)',
                  padding: '10px 14px',
                  background: '#fff',
                  border: '1px solid #d9e0e8',
                  borderRadius: 3,
                }}
              >
                {data.decision === 'accepted' ? 'Accepted' : 'Returned to applicant'} by{' '}
                {data.decided_by || 'unnamed reviewer'}
                {data.override ? ' · override recorded' : ''} ·{' '}
                <span className="mono">{data.decided_at?.slice(0, 16).replace('T', ' ')}</span>
                {data.note ? ` · ${data.note}` : ''}
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
              /* The two decisions lead, because deciding is the job. Fixing
                 the application and reading the label again are how a reviewer
                 gets to one, so they follow. An unverified record has no
                 determination to accept, so verification takes the front. */
              <div className="row">
                {data.verified ? (
                  <button className="btn btn-accept" onClick={() => setConfirming('accepted')}>
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
                  with the timestamp and, where it applies, the override flag.
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
        <div
          className="dialog-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label={`Label image for ${data.app_brand}`}
          tabIndex={-1}
          autoFocus
          onClick={() => setZoomed(false)}
        >
          <figure className="lightbox">
            <img
              src={imageUrl(data.specimen || data.filename)}
              alt={`Label image for ${data.app_brand}`}
            />
            <figcaption className="mono">{data.filename}</figcaption>
          </figure>
        </div>
      )}
    </div>
  )
}
