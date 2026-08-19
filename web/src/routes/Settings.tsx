import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiUrl } from '../api/client'
import type { RecordsPage } from '../api/client'

/**
 * Administration. The store is read as a normal web page — CSV exists only as a
 * file download (S13), so "view raw CSV" from the prototype is replaced by the
 * record table below.
 */
export function Settings() {
  const client = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [showStore, setShowStore] = useState(false)

  const records = useQuery({
    queryKey: ['records', ''],
    queryFn: () => api<RecordsPage>('/records'),
  })

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () =>
      api<{ provider: string; model: string; store_readable: boolean; images_writable: boolean }>(
        '/health',
      ),
  })

  const reset = useMutation({
    mutationFn: () =>
      api<{ reset_count: number }>('/fixtures', {
        method: 'POST',
        body: { mode: 'reset' },
        admin: true,
      }),
    onSuccess: (data) => {
      setConfirming(false)
      setMessage(
        `Store reset — ${data.reset_count} fixtures restored. The prior store was snapshotted first.`,
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
          <h1>Data &amp; verification settings</h1>
        </div>
      </div>

      <div className="grid-2" style={{ alignItems: 'start', gap: 20 }}>
        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700 }}>Record store</div>
          <p className="card-note">
            Applications, extractions and determinations persist to a SQLite system of record
            with an append-only audit log. {rows.length} records persisted · a CSV mirror is
            regenerated after every mutation.
          </p>
          <div className="stack" style={{ gap: 10, marginTop: 14 }}>
            <a className="btn btn-wide" href={apiUrl('/export/records.csv')} download>
              Export records as CSV
            </a>
            <button className="btn btn-quiet btn-wide" onClick={() => setShowStore((v) => !v)}>
              {showStore ? 'Hide record table' : 'View record table'}
            </button>
            {confirming ? (
              <div className="row">
                <button
                  className="btn btn-danger"
                  onClick={() => reset.mutate()}
                  disabled={reset.isPending}
                >
                  {reset.isPending && <span className="spinner spinner-dark" />}
                  Confirm reset
                </button>
                <button className="btn btn-quiet" onClick={() => setConfirming(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <button className="btn btn-danger btn-wide" onClick={() => setConfirming(true)}>
                Reset to sample data
              </button>
            )}
          </div>
          {confirming && (
            <p className="card-note">
              This snapshots the current store, wipes it, and restores the 25 bundled fixtures.
              Requires the admin token.
            </p>
          )}
          {message && <p className="card-note">{message}</p>}
        </div>

        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700 }}>Verification engine</div>
          <p className="card-note">
            A deterministic rules engine produces the verdict of record. The vision reader
            supplies observed values and may downgrade a verdict, never improve one.
          </p>
          <div className="check-row" style={{ marginTop: 12, alignItems: 'flex-start' }}>
            <div>
              <strong>Reader:</strong>{' '}
              <span className="mono">
                {health.data?.provider ?? '—'}
                {health.data?.model ? ` / ${health.data.model}` : ''}
              </span>
              <div style={{ fontWeight: 400, marginTop: 4 }}>
                Configured with <span className="mono">READER_PROVIDER</span>. When the provider
                is unreachable, verification falls back to local OCR and the engine string names
                the cause.
              </div>
            </div>
          </div>
          <ul className="bullets">
            <li>
              Target turnaround is under five seconds per label; elapsed time is recorded on
              every determination.
            </li>
            <li>
              Verdicts are field-scoped: content differences fail, formatting and unit
              differences route to review.
            </li>
            <li>
              Degraded captures lower extraction confidence and downgrade otherwise clean
              matches to review.
            </li>
            <li>
              Illegible fields fail with a request for replacement artwork rather than a silent
              guess.
            </li>
          </ul>
        </div>
      </div>

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
