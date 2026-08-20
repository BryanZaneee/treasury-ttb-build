import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RecordDetail, RecordRow } from '../api/client'
import { FIELD_LABEL } from '../lib/copy'
import { REVIEWER } from '../lib/session'
import { useEscape } from '../lib/dialog'
import { Pill } from './Pill'

/**
 * Confirmation for a bulk determination.
 *
 * Accepting a record that did not pass is an override, and acceptance test 8
 * requires the confirmation to name the fields that disagree. Doing that in bulk
 * means saying it for every record being overridden, not once in the abstract —
 * otherwise an auditor cannot tell the reviewer ever saw what they waived. The
 * list payload carries the verdict but not the field results, so those are
 * fetched for the non-match records in the selection before anything is sent.
 */
export function BulkDecisionDialog({
  decision,
  records,
  onCancel,
  onConfirm,
  pending,
}: {
  decision: 'accepted' | 'returned'
  records: RecordRow[]
  onCancel: () => void
  onConfirm: (reason: string) => void
  pending: boolean
}) {
  const [reason, setReason] = useState('')
  useEscape(onCancel)
  const overrides = records.filter((r) => r.result !== 'match')
  const needsOverrideDetail = decision === 'accepted' && overrides.length > 0

  const details = useQuery({
    queryKey: ['bulk-detail', overrides.map((r) => r.id).join(',')],
    enabled: needsOverrideDetail,
    queryFn: () =>
      Promise.all(overrides.map((r) => api<RecordDetail>(`/records/${r.id}`))),
  })

  const accepting = decision === 'accepted'

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-head">
          <h2 id="bulk-title">
            {accepting ? 'Accept' : 'Return'} {records.length} record
            {records.length === 1 ? '' : 's'}
          </h2>
          <p className="card-note">
            Recorded against <strong>{REVIEWER.name}</strong> with a timestamp
            {accepting && overrides.length > 0 ? ' and an override flag' : ''}.
          </p>
        </div>

        <div className="dialog-body">
          {!accepting && (
            <>
              <div className="banner" style={{ marginBottom: 14 }}>
                <div className="banner-mark" aria-hidden="true">
                  !
                </div>
                <div className="banner-text">
                  A returned record is not reopenable. The applicant files afresh.
                </div>
              </div>
              <label className="field">
                <span className="field-label">Reason returned to applicant</span>
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Shared by every record in this selection"
                />
              </label>
            </>
          )}

          {needsOverrideDetail && (
            <>
              <div className="banner" style={{ marginBottom: 12 }}>
                <div className="banner-mark" aria-hidden="true">
                  !
                </div>
                <div className="banner-text">
                  <strong>
                    {records.length === 1
                      ? 'This record did not pass verification.'
                      : `${overrides.length} of these did not pass verification.`}
                  </strong>{' '}
                  {records.length === 1
                    ? 'Accepting it overrides the fields listed below.'
                    : 'Accepting them overrides the fields listed below, on each record.'}
                </div>
              </div>
              {details.isLoading && (
                <p className="card-note">
                  <span className="spinner spinner-dark" /> Loading the disagreeing fields…
                </p>
              )}
              {details.data?.map((d) => (
                <div className="override-row" key={d.id}>
                  <Pill verdict={d.result} small />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{d.app_brand}</div>
                    <div className="override-fields mono">{d.id}</div>
                    <div className="override-fields">
                      {d.field_results
                        .filter((f) => f.verdict !== 'match')
                        .map((f) => FIELD_LABEL[f.field_key] ?? f.field_key)
                        .join(', ') || 'no field detail recorded'}
                    </div>
                  </div>
                </div>
              ))}
            </>
          )}

          {accepting && overrides.length === 0 && (
            <p className="card-note">
              {records.length === 1 ? 'This record' : 'Every selected record'} passed
              verification. No override is required.
            </p>
          )}
        </div>

        <div className="dialog-foot">
          <button
            className={`btn ${accepting ? 'btn-accept' : 'btn-return'}`}
            disabled={pending || (needsOverrideDetail && details.isLoading)}
            onClick={() => onConfirm(reason)}
          >
            {pending && <span className="spinner" />}
            Confirm {accepting ? 'acceptance' : 'return'}
          </button>
          <button className="btn btn-quiet" onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
