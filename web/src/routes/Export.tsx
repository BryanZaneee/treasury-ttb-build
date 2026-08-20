import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, freshUrl } from '../api/client'
import type { Health, RecordsPage } from '../api/client'

/**
 * Export and store administration. The store is read as a normal web page — CSV
 * exists only as a file download (S13), so "view raw CSV" from the prototype is
 * replaced by the record table below.
 */
export function Export() {
  const client = useQueryClient()
  const [confirming, setConfirming] = useState<null | 'reset' | 'empty'>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [showStore, setShowStore] = useState(false)

  const records = useQuery({
    queryKey: ['records', ''],
    queryFn: () => api<RecordsPage>('/records'),
  })

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
  })

  const reset = useMutation({
    mutationFn: (mode: 'reset' | 'empty') =>
      api<{ reset_count: number }>('/fixtures', {
        method: 'POST',
        body: { mode },
        admin: true,
      }),
    onSuccess: (data, mode) => {
      setConfirming(null)
      setMessage(
        mode === 'empty'
          ? 'Every record was removed. A copy of the old store was saved first.'
          : `The example set is loaded — ${data.reset_count} applications to work through. A copy of the old store was saved first.`,
      )
      client.invalidateQueries({ queryKey: ['records'] })
    },
    onError: (e) => setMessage(String(e)),
  })

  const rows = records.data?.records ?? []

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>Records</h1>
        </div>
      </div>

      <div className="grid-2" style={{ gap: 20 }}>
        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700 }}>Applications on file</div>
          <p className="card-note">
            {rows.length} application{rows.length === 1 ? '' : 's'} have been filed. Every
            determination is kept with the reviewer who made it, so the record of what was
            decided outlives the session it was decided in.
          </p>
          <p className="card-note">
            To file a spreadsheet of applications, upload it with its label images on Batch
            upload — nothing is written until you have checked the pairing.
          </p>
          <div className="stack" style={{ gap: 10, marginTop: 14 }}>
            <a className="btn btn-wide" href={freshUrl('/export/records.csv')} download>
              Export records as CSV
            </a>
            <button className="btn btn-quiet btn-wide" onClick={() => setShowStore((v) => !v)}>
              {showStore ? 'Hide record table' : 'View record table'}
            </button>
            <button className="btn btn-quiet btn-wide" onClick={() => setConfirming('reset')}>
              Load the example set
            </button>
            <button className="btn btn-danger btn-wide" onClick={() => setConfirming('empty')}>
              Remove all records
            </button>
          </div>
          {message && <p className="card-note">{message}</p>}
        </div>

        <div className="card card-pad">
          <div className="row">
            <div style={{ fontSize: 15, fontWeight: 700 }}>How a label is checked</div>
            {/* The bubble is CSS on the element itself: a native `title` needs a
                second of hover to appear and is easy to miss entirely. */}
            <span
              className="help-dot push"
              tabIndex={0}
              role="note"
              data-tip={
                'The AI reads the label picture and writes down the seven things it can see. ' +
                'It does not decide the outcome. Each of those readings is then compared, by ' +
                'a fixed set of checks, against what the applicant filed. The AI can flag a ' +
                'problem or add a note; it can never clear one.'
              }
            >
              ?
            </span>
          </div>
          <p className="card-note">
            The AI reads the label and reports what it can see. The result is then decided by a
            fixed set of checks against the application as filed — the AI can raise a problem,
            never clear one.
          </p>
          <div className="readout">
            <div>
              <strong>Reader:</strong>{' '}
              <span className="mono">
                {health.data?.provider ?? '—'}
                {health.data?.model ? ` / ${health.data.model}` : ''}
              </span>
              <div style={{ fontWeight: 400, marginTop: 4 }}>
                <a
                  href="https://platform.openai.com/docs/models"
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  Learn more about GPT-5.6 Luna
                </a>
              </div>
            </div>
          </div>
          <ul className="bullets">
            <li>Most labels come back in a few seconds.</li>
            <li>
              A field is checked on its own: wrong content fails, while wording or unit
              differences are sent for review rather than refused outright.
            </li>
            <li>
              A blurred or glared photo lowers confidence, so an otherwise clean label is sent
              for review rather than passed.
            </li>
            <li>
              A field nobody could read is failed with a request for better artwork, never
              guessed at.
            </li>
          </ul>
        </div>
      </div>

      {confirming && (
        <div className="dialog-backdrop" role="presentation" onClick={() => setConfirming(null)}>
          <div
            className="dialog dialog-sm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dialog-head">
              <h2 id="reset-title">
                {confirming === 'empty' ? 'Remove all records' : 'Load the example set'}
              </h2>
            </div>
            <div className="dialog-body">
              <div className="banner">
                <div className="banner-mark" aria-hidden="true">
                  !
                </div>
                <div className="banner-text">
                  {confirming === 'empty' ? (
                    <>
                      Every application and label image on file is removed, leaving an empty
                      inbox for your own data.
                    </>
                  ) : (
                    <>
                      Everything on file is replaced with thirteen example applications to
                      practise on — three still to check, three that matched, three in review,
                      four that failed, and three already decided.
                    </>
                  )}{' '}
                  A copy of the current store is saved first.
                </div>
              </div>
              <p className="card-note">
                {rows.length} application{rows.length === 1 ? '' : 's'} will be replaced.
              </p>
            </div>
            <div className="dialog-foot">
              <button
                className={confirming === 'empty' ? 'btn btn-danger' : 'btn'}
                onClick={() => reset.mutate(confirming)}
                disabled={reset.isPending}
              >
                {reset.isPending && <span className="spinner" />}
                {confirming === 'empty' ? 'Yes, remove everything' : 'Yes, load the example set'}
              </button>
              <button className="btn btn-quiet" onClick={() => setConfirming(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {showStore && (
        <div className="card" style={{ marginTop: 20 }}>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>COLA ID</th>
                  <th>Received</th>
                  <th>Applicant</th>
                  <th>Brand</th>
                  <th>Class / type</th>
                  <th>ABV</th>
                  <th>Net</th>
                  <th>Result</th>
                  <th>Decision</th>
                  <th>Engine</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td className="mono">{r.received.slice(0, 10)}</td>
                    <td>{r.applicant}</td>
                    <td>{r.app_brand}</td>
                    <td>{r.app_class_type}</td>
                    <td className="mono">{r.app_alcohol_content}</td>
                    <td className="mono">{r.app_net_contents}</td>
                    <td>{r.result ?? '—'}</td>
                    <td>{r.decision ?? '—'}</td>
                    <td className="mono" style={{ fontSize: 11.5 }}>
                      {r.engine ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length === 0 && (
            <div className="empty">
              <div className="empty-title">The store is empty</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
