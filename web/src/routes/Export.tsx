import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, download, freshUrl, hasAdminToken, setAdminToken } from '../api/client'
import type { Health, RecordsPage, StoreImport } from '../api/client'
import { useEscape } from '../lib/dialog'
import { Dialog } from '../components/Dialog'

/**
 * Export and store administration. CSV exists only as a download (S13), so the
 * prototype's "view raw CSV" is the record table below.
 */
export function Export() {
  const client = useQueryClient()
  const [confirming, setConfirming] = useState<null | 'reset' | 'empty'>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [showStore, setShowStore] = useState(false)
  const restoreRef = useRef<HTMLInputElement>(null)
  // Set when an admin action is attempted with no token: it holds the action
  // until one is supplied, so the reviewer is asked once rather than per click.
  const [pending, setPending] = useState<null | (() => void)>(null)
  const [token, setToken] = useState('')
  useEscape(() => {
    setConfirming(null)
    setPending(null)
  })

  /** Run an admin action, asking for the token first when there is not one. */
  const asAdmin = (action: () => void) => {
    if (hasAdminToken()) action()
    else setPending(() => action)
  }

  const records = useQuery({
    queryKey: ['records', ''],
    queryFn: () => api<RecordsPage>('/records'),
  })

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: 60_000,
  })

  // S11's other half: the reviewer export drops columns, so the file that
  // restores a store is /export/backup.csv. Both are offered, named for use.
  const restore = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.set('csv_file', file)
      form.set('mode', 'replace')
      return api<StoreImport>('/store/import', {
        method: 'POST',
        form,
        admin: true,
      })
    },
    onSuccess: (data) => {
      client.invalidateQueries({ queryKey: ['records'] })
      setMessage(
        data.errors.length > 0
          ? `Restored ${data.imported} records. ${data.errors.length} row${data.errors.length === 1 ? '' : 's'} could not be read: ${data.errors.slice(0, 3).join('; ')}`
          : `Restored ${data.imported} record${data.imported === 1 ? '' : 's'} from the backup.`,
      )
    },
    onError: (e) => setMessage(`The backup could not be restored. ${String(e)}`),
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
          : `The example set is loaded: ${data.reset_count} applications to work through. A copy of the old store was saved first.`,
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
            upload. Nothing is written until you have checked the pairing.
          </p>
          <div className="stack" style={{ gap: 10, marginTop: 14 }}>
            <a className="btn btn-wide" href={freshUrl('/export/records.csv')} download>
              Export records as CSV
            </a>
            <button className="btn btn-wide" onClick={() => asAdmin(() => setConfirming('reset'))}>
              Load the example set
            </button>
            <button
              className="btn btn-quiet btn-wide"
              onClick={() =>
                asAdmin(() => {
                  // Admin-gated (it carries applicant and reviewer names), so it
                  // is fetched with the header rather than linked to directly.
                  download('/export/backup.csv', 'records-backup.csv', true).catch((e) =>
                    setMessage(`The backup could not be downloaded. ${String(e)}`),
                  )
                })
              }
            >
              Download a restorable backup
            </button>
            <button
              className="btn btn-quiet btn-wide"
              disabled={restore.isPending}
              onClick={() => asAdmin(() => restoreRef.current?.click())}
            >
              {restore.isPending && <span className="spinner" />}
              Restore from a backup
            </button>
            <button className="btn btn-quiet btn-wide" onClick={() => setShowStore((v) => !v)}>
              {showStore ? 'Hide record table' : 'View record table'}
            </button>
            <button
              className="btn btn-danger btn-wide"
              onClick={() => asAdmin(() => setConfirming('empty'))}
            >
              Remove all records
            </button>
          </div>
          <input
            ref={restoreRef}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) restore.mutate(file)
              e.target.value = ''
            }}
          />
          {message && <p className="card-note">{message}</p>}
        </div>

        <div className="card card-pad">
          <div className="row">
            <div style={{ fontSize: 15, fontWeight: 700 }}>How a label is checked</div>
            {/* CSS, not a native `title`: that needs a second of hover to appear. */}
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
            fixed set of checks against the application as filed. The AI can raise a problem,
            never clear one.
          </p>
          <div className="readout">
            <div>
              <strong>Reader:</strong>{' '}
              <span className="mono">
                {health.data?.provider ?? 'None'}
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

      {pending && (
        <Dialog
          title="Administrator token required"
          titleId="admin-token-title"
          onClose={() => setPending(null)}
          footer={
            <>
              <button
                className="btn"
                disabled={!token.trim()}
                onClick={() => {
                  setAdminToken(token)
                  setToken('')
                  const action = pending
                  setPending(null)
                  action()
                }}
              >
                Continue
              </button>
              <button className="btn btn-quiet" onClick={() => setPending(null)}>
                Cancel
              </button>
            </>
          }
        >
          <p className="card-note">
            Replacing the store, resetting it and downloading a full backup are
            administrator actions. Enter the shared administrator token to continue; it is
            kept for this browser tab only and is never written into the page.
          </p>
          <label className="field">
            <span>Administrator token</span>
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== 'Enter' || !token.trim()) return
                setAdminToken(token)
                setToken('')
                const action = pending
                setPending(null)
                action()
              }}
            />
          </label>
        </Dialog>
      )}

      {confirming && (
        <Dialog
          title={confirming === 'empty' ? 'Remove all records' : 'Load the example set'}
          titleId="reset-title"
          onClose={() => setConfirming(null)}
          footer={
            <>
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
            </>
          }
        >
          <div className="banner">
            <div className="banner-mark" aria-hidden="true">
              !
            </div>
            <div className="banner-text">
              {confirming === 'empty'
                ? 'Every application and label image on file is removed, leaving an empty inbox for your own data.'
                : 'Everything on file is replaced with thirteen example applications to practise on: three still to check, three that matched, three in review, four that failed, and three already decided.'}{' '}
              A copy of the current store is saved first.
            </div>
          </div>
          <p className="card-note">
            {rows.length} application{rows.length === 1 ? '' : 's'} will be replaced.
          </p>
        </Dialog>
      )}

      {showStore && (
        <div className="card" style={{ marginTop: 20 }}>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>COLA ID</th>
                  <th>Received</th>
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
                    <td>{r.app_brand}</td>
                    <td>{r.app_class_type}</td>
                    <td className="mono">{r.app_alcohol_content}</td>
                    <td className="mono">{r.app_net_contents}</td>
                    <td>{r.result ?? 'Pending'}</td>
                    <td>{r.decision ?? 'Not decided'}</td>
                    <td className="mono" style={{ fontSize: 11.5 }}>
                      {r.engine ?? 'None'}
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
