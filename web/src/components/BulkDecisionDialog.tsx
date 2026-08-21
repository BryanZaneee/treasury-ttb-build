import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RecordDetail, RecordRow } from '../api/client'
import { FIELD_LABEL, contestedAccept } from '../lib/copy'
import { REVIEWER } from '../lib/session'
import { useEscape } from '../lib/dialog'
import { Pill } from './Pill'
import { Dialog } from './Dialog'

/**
 * Confirmation for a bulk determination. Acceptance test 8 wants the disagreeing
 * fields named, and in bulk that means per record - otherwise an auditor cannot
 * tell the reviewer saw what they waived. The list payload carries the verdict
 * but not the field results, so those are fetched first.
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
  // Only a failed check is named field by field; a presentation difference is
  // still recorded as an override, without the challenge.
  const contested = records.filter((r) => contestedAccept(r.result))
  const needsOverrideDetail = decision === 'accepted' && contested.length > 0

  const details = useQuery({
    queryKey: ['bulk-detail', contested.map((r) => r.id).join(',')],
    enabled: needsOverrideDetail,
    queryFn: () =>
      Promise.all(contested.map((r) => api<RecordDetail>(`/records/${r.id}`))),
  })

  const accepting = decision === 'accepted'

  return (
    <Dialog
      title={`${accepting ? 'Accept' : 'Return'} ${records.length} record${records.length === 1 ? '' : 's'}`}
      titleId="bulk-title"
      wide
      onClose={onCancel}
      subtitle={
        <p className="card-note">
          Recorded against <strong>{REVIEWER.name}</strong> with a timestamp.
        </p>
      }
      footer={
        <>
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
        </>
      }
    >
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
                  : `${contested.length} of these did not pass verification.`}
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
    </Dialog>
  )
}
