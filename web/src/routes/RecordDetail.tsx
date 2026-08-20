import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, imageUrl } from '../api/client'
import type { Health, RecordDetail as Detail } from '../api/client'
import { Pill } from '../components/Pill'
import { kindOf } from '../lib/verdict'
import { FIELD_LABEL, RESULT_COPY, fieldValues } from '../lib/copy'
import { REVIEWER } from '../lib/session'
import { QueueNav } from '../components/QueueNav'
import { useEscape } from '../lib/dialog'
import { useToast } from '../lib/toast'
import { FALLBACK_BODY, FALLBACK_TITLE, readByFallback } from '../lib/fallback'

/** Minimised state and the open record survive reload, per device (S10). */
const MINIMISED_KEY = 'ttb.detail.minimised'

export function RecordDetail() {
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
  const [minimised, setMinimised] = useState(() => localStorage.getItem(MINIMISED_KEY) === '1')
  const [zoomed, setZoomed] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<null | 'accepted' | 'returned'>(null)
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

  const verify = useMutation({
    mutationFn: () => api<Detail>(`/records/${id}/verify`, { method: 'POST' }),
    onSuccess: (updated) => {
      if (readByFallback(updated, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
      client.invalidateQueries({ queryKey: ['record', id] })
      client.invalidateQueries({ queryKey: ['records'] })
    },
    onError: (e) => toast({ kind: 'error', title: 'Verification failed', body: String(e) }),
  })

  const decide = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/records/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      setError(null)
      setConfirming(null)
      client.invalidateQueries({ queryKey: ['record', id] })
      client.invalidateQueries({ queryKey: ['records'] })
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
  const toggle = () => {
    const next = !minimised
    setMinimised(next)
    localStorage.setItem(MINIMISED_KEY, next ? '1' : '0')
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

          <div className="card card-pad">
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
              <div className="card-title">Application data</div>
              <button className="btn-link" onClick={toggle}>
                {minimised ? 'Expand' : 'Minimise'}
              </button>
            </div>
            {!minimised && (
              <div className="stack" style={{ gap: 11 }}>
                {(
                  [
                    ['app_brand', 'Brand name'],
                    ['app_class_type', 'Class / type'],
                    ['app_alcohol_content', 'Alcohol content'],
                    ['app_net_contents', 'Net contents'],
                    ['app_producer', 'Bottler / producer'],
                    ['app_origin', 'Country of origin'],
                  ] as const
                ).map(([key, label]) => (
                  <div key={key}>
                    <span className="field-label">{label}</span>
                    <div
                      style={{
                        border: '1px solid var(--field)',
                        borderRadius: 3,
                        padding: '9px 10px',
                        fontSize: 13,
                        background: 'var(--sunk-2)',
                        minHeight: 40,
                      }}
                    >
                      {(data[key] as string) || (
                        <span style={{ color: 'var(--ink-6)' }}>Not declared</span>
                      )}
                    </div>
                  </div>
                ))}
                {/* A label, not a div: the text has to be the checkbox's own
                    label or a screen reader announces an unnamed control. */}
                <label className="check-row">
                  <input type="checkbox" checked={data.app_warning_declared} readOnly />
                  <span>Applicant declares required government warning</span>
                </label>
              </div>
            )}
            <button
              className="btn btn-wide"
              style={{ marginTop: 14 }}
              onClick={() => verify.mutate()}
              disabled={verify.isPending}
            >
              {verify.isPending && <span className="spinner" />}
              {data.verified ? 'Re-run AI verification' : 'Run AI verification'}
            </button>
          </div>
        </div>

        <div className="card">
          {header}

          {data.verified ? (
            <>
              {data.result === 'invalid' ? (
                /* No fields were adjudicated (PRD §3.2 ext), so the comparison
                   table would be four column headers over nothing. */
                <div className="empty">
                  <div className="empty-title">Nothing to compare</div>
                  <div className="empty-hint">
                    The reader found no alcohol beverage label in this image, so no field
                    was adjudicated. Return the record and ask the applicant for the label
                    artwork.
                  </div>
                </div>
              ) : (
                <>
              <div className="fields-head">
                <div>Item</div>
                <div>Application says</div>
                <div>Label shows</div>
                <div>Result</div>
              </div>
              {data.field_results.map((f) => {
                const values = fieldValues(f)
                return (
                <div className="fields-row" key={f.field_key}>
                  <div>
                    <div className="fields-name">{FIELD_LABEL[f.field_key] ?? f.field_key}</div>
                    {f.note && <div className="fields-note">{f.note}</div>}
                  </div>
                  <div className={`fields-value${values.recorded ? '' : ' fields-unrecorded'}`}>
                    {values.app}
                  </div>
                  <div className={`fields-value${values.recorded ? '' : ' fields-unrecorded'}`}>
                    {values.label}
                  </div>
                  <div>
                    <Pill verdict={f.verdict} small />
                  </div>
                </div>
                )
              })}
                </>
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
                ) : confirming === null ? (
                  <div className="row">
                    <button className="btn btn-accept" onClick={() => setConfirming('accepted')}>
                      Accept determination
                    </button>
                    <button className="btn btn-return" onClick={() => setConfirming('returned')}>
                      Return to applicant
                    </button>
                  </div>
                ) : (
                  <div style={{ width: '100%' }}>
                    {error && <div className="banner-error">{error}</div>}
                    {confirming === 'accepted' && needsOverride && (
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
                      This determination will be recorded against{' '}
                      <strong>{REVIEWER.name}</strong>, with the timestamp and, where it
                      applies, the override flag.
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
                  A returned record is not reopenable. The applicant files afresh. Every
                  determination appends to the audit log.
                </div>
              </div>
            </>
          ) : (
            <div className="placeholder placeholder-flush">
              <div className="placeholder-title">Not yet verified</div>
              <div className="placeholder-hint">
                Confirm the application data on the left, then run AI verification. The service
                reads the label image and compares every required field against the
                application of record.
              </div>
            </div>
          )}
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
