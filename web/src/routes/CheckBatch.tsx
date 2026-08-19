import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, apiUrl } from '../api/client'
import type { Job, StagedBatch } from '../api/client'

const BUCKET: Record<string, { label: string; pill: string }> = {
  matched: { label: 'Matched', pill: 'pill-match' },
  matched_fuzzy: { label: 'Matched · extension differs', pill: 'pill-review' },
  missing_image: { label: 'No image', pill: 'pill-pending' },
  ambiguous: { label: 'Ambiguous', pill: 'pill-fail' },
}

const REQUIRED =
  'filename, brand_name, class_type, alcohol_content, net_contents, producer, country_of_origin, government_warning, applicant'

export function CheckBatch() {
  const [batch, setBatch] = useState<StagedBatch | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [verifyNow, setVerifyNow] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const csvRef = useRef<HTMLInputElement>(null)
  const imgRef = useRef<HTMLInputElement>(null)
  const [csvName, setCsvName] = useState('No file selected')
  const [imgCount, setImgCount] = useState('No images selected')
  const client = useQueryClient()

  const loadSample = useMutation({
    mutationFn: () =>
      api<{ batch: StagedBatch }>('/fixtures', { method: 'POST', body: { mode: 'stage' } }),
    onSuccess: (data) => {
      setBatch(data.batch)
      setJob(null)
      setError(null)
    },
    onError: (e) => setError(String(e)),
  })

  const stage = useMutation({
    mutationFn: () => {
      const form = new FormData()
      const csv = csvRef.current?.files?.[0]
      if (!csv) throw new Error('Choose an application CSV first.')
      form.set('applications_csv', csv)
      for (const file of imgRef.current?.files ?? []) form.append('images', file)
      return api<StagedBatch>('/batches/stage', { method: 'POST', form })
    },
    onSuccess: (data) => {
      setBatch(data)
      setJob(null)
      setError(null)
    },
    onError: (e) => setError(String(e)),
  })

  const commit = useMutation({
    mutationFn: async () => {
      const started = await api<Job>('/jobs', {
        method: 'POST',
        body: { scope: 'batch', batch_id: batch!.batch_id, verify_now: verifyNow },
      })
      let state = started
      while (state.state === 'running') {
        setJob(state)
        await new Promise((r) => setTimeout(r, 350))
        state = await api<Job>(`/jobs/${started.id}`)
      }
      return state
    },
    onSuccess: (finished) => {
      setJob(finished)
      client.invalidateQueries({ queryKey: ['records'] })
    },
    onError: (e) => setError(String(e)),
  })

  const committable = batch ? batch.rows.filter((r) => r.bucket !== 'ambiguous').length : 0

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Bulk intake</div>
          <h1>Check a batch</h1>
          <p className="lede">
            For importers filing many applications at once. Upload an application CSV together
            with the matching label images, then verify the whole batch in one pass.
          </p>
        </div>
      </div>

      <div className="batch-grid">
        <div className="card card-pad area-step1">
            <div className="row">
              <div className="card-title">Step 1 · Application CSV</div>
              <a className="push" href={apiUrl('/export/template.csv')} download>
                Download blank template
              </a>
            </div>
            <p className="card-note">Required columns: {REQUIRED}</p>
            <div className="grid-2" style={{ marginTop: 12 }}>
              <button className="dropzone" onClick={() => csvRef.current?.click()}>
                <div className="dropzone-title">Choose CSV file</div>
                <div className="dropzone-hint">{csvName}</div>
              </button>
              <button className="dropzone" onClick={() => imgRef.current?.click()}>
                <div className="dropzone-title">Choose label images</div>
                <div className="dropzone-hint">{imgCount}</div>
              </button>
            </div>
            <input
              ref={csvRef}
              type="file"
              accept=".csv"
              hidden
              onChange={(e) => setCsvName(e.target.files?.[0]?.name ?? 'No file selected')}
            />
            <input
              ref={imgRef}
              type="file"
              accept="image/*"
              multiple
              hidden
              onChange={(e) =>
                setImgCount(
                  e.target.files?.length
                    ? `${e.target.files.length} images selected`
                    : 'No images selected',
                )
              }
            />
            <div className="row" style={{ marginTop: 12 }}>
              <button
                className="btn btn-quiet"
                onClick={() => stage.mutate()}
                disabled={stage.isPending}
              >
                {stage.isPending && <span className="spinner spinner-dark" />}
                Stage upload
              </button>
            </div>
          </div>

        <div className="card card-pad area-step2">
            <div className="card-title">Step 2 · Staged applications</div>
            {error && (
              <div className="banner-error" style={{ marginTop: 12, marginBottom: 0 }}>
                {error}
              </div>
            )}
            {!batch ? (
              <div className="dropzone" style={{ marginTop: 12, padding: 40 }}>
                <div className="dropzone-hint" style={{ fontSize: 13.5 }}>
                  No applications staged yet.
                  <br />
                  Upload a CSV above or load the bundled sample batch.
                </div>
              </div>
            ) : (
              <>
                <div className="row" style={{ marginTop: 12 }}>
                  {(['matched', 'matched_fuzzy', 'missing_image', 'ambiguous'] as const).map(
                    (b) => (
                      <span key={b} className={`pill ${BUCKET[b].pill}`}>
                        {BUCKET[b].label} {batch.summary[b]}
                      </span>
                    ),
                  )}
                  <span className="push mono" style={{ fontSize: 11.5, color: 'var(--ink-6)' }}>
                    {batch.batch_id}
                  </span>
                </div>
                {batch.summary.unused_images.length > 0 && (
                  <p className="card-note">
                    {batch.summary.unused_images.length} uploaded image
                    {batch.summary.unused_images.length === 1 ? '' : 's'} no row claims:{' '}
                    <span className="mono">{batch.summary.unused_images.join(', ')}</span>
                  </p>
                )}
                {batch.blocks_commit && (
                  <div className="banner-error" style={{ marginTop: 12 }}>
                    Commit is blocked while any row is ambiguous. Rename or remove the duplicate
                    images listed below, then stage again.
                  </div>
                )}
                <div className="scroll-x" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Brand</th>
                        <th>Applicant</th>
                        <th>Filename</th>
                        <th>Pairing</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batch.rows.map((r) => (
                        <tr key={r.row}>
                          <td className="num">{r.row}</td>
                          <td>{r.brand}</td>
                          <td>{r.applicant}</td>
                          <td className="mono" style={{ fontSize: 12 }}>
                            {r.filename}
                          </td>
                          <td>
                            <span className={`pill pill-sm ${BUCKET[r.bucket].pill}`}>
                              {BUCKET[r.bucket].label}
                            </span>
                          </td>
                          <td style={{ fontSize: 12, color: 'var(--ink-5)' }}>
                            {r.errors.join('; ')}
                            {r.candidate_filenames.length > 0 && (
                              <div className="mono">{r.candidate_filenames.join(', ')}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

        <div className="card card-pad area-run">
            <div className="card-title">Step 3 · Run</div>
            <label className="check-row" style={{ marginTop: 12, alignItems: 'flex-start' }}>
              <input
                type="checkbox"
                checked={verifyNow}
                onChange={(e) => setVerifyNow(e.target.checked)}
              />
              <span style={{ fontWeight: 400 }}>
                <strong>Verify on intake.</strong> Leave unchecked to file the batch as awaiting
                verification.
              </span>
            </label>
            <button
              className="btn btn-wide"
              style={{ marginTop: 12 }}
              onClick={() => commit.mutate()}
              disabled={!batch || batch.blocks_commit || commit.isPending}
            >
              {commit.isPending && <span className="spinner" />}
              {batch ? `File and verify ${committable} rows` : 'File and verify batch'}
            </button>
            {commit.isPending && job && (
              <p className="card-note">
                {job.completed}/{job.total} verified…
              </p>
            )}
            {commit.isSuccess && job && (
              <p className="card-note">
                Committed {job.committed} records · verified {job.completed}/{job.total} ·{' '}
                {Object.entries(job.verdicts)
                  .map(([k, v]) => `${v} ${k}`)
                  .join(' · ')}
                {job.failed > 0 && ` · ${job.failed} failed`}. <Link to="/inbox">Open the inbox</Link>
                .
              </p>
            )}
          </div>

        <div className="card card-pad area-nofiles" style={{ background: 'var(--sunk-2)' }}>
            <div className="card-title">No files handy?</div>
            <p className="card-note">
              Load a bundled sample batch of 25 applications with matching specimens — clean
              artwork, casing differences, missing and altered warnings, and degraded captures.
            </p>
            <button
              className="btn btn-quiet btn-wide"
              style={{ marginTop: 12 }}
              onClick={() => loadSample.mutate()}
              disabled={loadSample.isPending}
            >
              {loadSample.isPending && <span className="spinner spinner-dark" />}
              Load bundled sample batch
            </button>
          </div>
      </div>
    </div>
  )
}
