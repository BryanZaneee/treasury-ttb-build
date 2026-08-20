import { Fragment, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, apiUrl, imageUrl } from '../api/client'
import type { Job, StagedBatch, StagedRow } from '../api/client'

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
  // Staging is about pairing names to files, so the only thing a row has to
  // show is the specimen and the name it was filed under. Brand and applicant
  // are the application's business and are checked at verification.
  const [expanded, setExpanded] = useState<number | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const csvRef = useRef<HTMLInputElement>(null)
  const imgRef = useRef<HTMLInputElement>(null)
  const [csvName, setCsvName] = useState('No file selected')
  const [imgCount, setImgCount] = useState('No images selected')
  const client = useQueryClient()

  const staged = (data: StagedBatch) => {
    setBatch(data)
    setError(null)
  }

  const loadSample = useMutation({
    mutationFn: () =>
      api<{ batch: StagedBatch }>('/fixtures', { method: 'POST', body: { mode: 'stage' } }),
    onSuccess: (data) => {
      staged(data.batch)
      setJob(null)
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
      staged(data)
      setJob(null)
    },
    onError: (e) => setError(String(e)),
  })

  const assign = useMutation({
    mutationFn: ({ row, image }: { row: number; image: string | null }) =>
      api<StagedBatch>(`/batches/${batch!.batch_id}/rows/${row}/image`, {
        method: 'POST',
        body: { image },
      }),
    onSuccess: staged,
    onError: (e) => setError(String(e)),
  })

  // Removing the image, not just the pairing: an uploaded file nobody wants in
  // this batch stops being offered to every other row's picker too.
  const discard = useMutation({
    mutationFn: (name: string) =>
      api<StagedBatch>(
        `/batches/${batch!.batch_id}/images/${encodeURIComponent(name)}`,
        { method: 'DELETE' },
      ),
    onSuccess: staged,
    onError: (e) => setError(String(e)),
  })

  const uploadRow = useMutation({
    mutationFn: ({ row, file }: { row: number; file: File }) => {
      const form = new FormData()
      form.set('image', file)
      return api<StagedBatch>(`/batches/${batch!.batch_id}/rows/${row}/upload`, {
        method: 'POST',
        form,
      })
    },
    onSuccess: staged,
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
  const busy = assign.isPending || discard.isPending || uploadRow.isPending

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
            <p className="card-note">
              An exported records CSV works here too — its column names are recognised and
              its extra columns ignored.
            </p>
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
              <div className="dropzone batch-empty" style={{ marginTop: 12, padding: 40 }}>
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
                  <>
                    <p className="card-note">
                      {batch.summary.unused_images.length} uploaded image
                      {batch.summary.unused_images.length === 1 ? '' : 's'} no row claims. Pair
                      one with a row using the Image column below, or remove it with the ×.
                    </p>
                    <div className="unused-strip">
                      {batch.summary.unused_images.map((name) => (
                        <figure key={name}>
                          <span className="thumb thumb-lg">
                            <button
                              type="button"
                              className="thumb-open"
                              aria-label={`View ${name}`}
                              onClick={() => setPreview(name)}
                            >
                              <img src={imageUrl(name)} alt="" />
                            </button>
                            <button
                              type="button"
                              className="thumb-x"
                              aria-label={`Remove ${name} from this batch`}
                              disabled={busy}
                              onClick={() => discard.mutate(name)}
                            >
                              ×
                            </button>
                          </span>
                          <figcaption className="mono">{name}</figcaption>
                        </figure>
                      ))}
                    </div>
                  </>
                )}
                {batch.blocks_commit && (
                  <div className="banner-error" style={{ marginTop: 12 }}>
                    Commit is blocked while any row is ambiguous. Pick the right image for each
                    one in the Image column below — no need to re-upload the batch.
                  </div>
                )}
                <div className="scroll-x" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Label</th>
                        <th>Filename</th>
                        <th>Pairing</th>
                        <th>Image</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {batch.rows.map((r) => (
                        <Fragment key={r.row}>
                          <tr>
                            <td className="num">{r.row}</td>
                            <td>
                              <button
                                type="button"
                                className="thumb"
                                aria-label={`Expand row ${r.row}`}
                                onClick={() =>
                                  setExpanded(expanded === r.row ? null : r.row)
                                }
                              >
                                {r.image ? (
                                  <img src={imageUrl(r.image)} alt="" />
                                ) : (
                                  <span className="thumb-empty">none</span>
                                )}
                              </button>
                            </td>
                            <td className="mono" style={{ fontSize: 12 }}>
                              {r.filename}
                            </td>
                            <td>
                              <span className={`pill pill-sm ${BUCKET[r.bucket].pill}`}>
                                {BUCKET[r.bucket].label}
                              </span>
                              {r.errors.length > 0 && (
                                <div
                                  style={{ fontSize: 11, color: 'var(--ink-5)', marginTop: 4 }}
                                >
                                  {r.errors.join('; ')}
                                </div>
                              )}
                            </td>
                            <td>
                              <div className="image-cell">
                                <button
                                  type="button"
                                  className="cell-x"
                                  aria-label={`Remove ${r.image ?? 'image'} from this batch`}
                                  disabled={!r.image || busy}
                                  onClick={() => r.image && discard.mutate(r.image)}
                                >
                                  ×
                                </button>
                                <select
                                  value={r.image ?? ''}
                                  disabled={busy}
                                  aria-label={`Image for row ${r.row}`}
                                  onChange={(e) =>
                                    assign.mutate({ row: r.row, image: e.target.value || null })
                                  }
                                >
                                  <option value="">— no image —</option>
                                  {/* Its own pairing, the candidates that made it
                                      ambiguous, and anything no other row claimed. */}
                                  {[
                                    ...new Set([
                                      ...(r.image ? [r.image] : []),
                                      ...r.candidate_filenames,
                                      ...batch.summary.unused_images,
                                    ]),
                                  ].map((name) => (
                                    <option key={name} value={name}>
                                      {name}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            </td>
                            <td>
                              <button
                                type="button"
                                className={`caret${expanded === r.row ? ' open' : ''}`}
                                aria-expanded={expanded === r.row}
                                aria-label={`Expand row ${r.row}`}
                                onClick={() =>
                                  setExpanded(expanded === r.row ? null : r.row)
                                }
                              >
                                ▾
                              </button>
                            </td>
                          </tr>
                          {expanded === r.row && (
                            <tr className="staged-expand">
                              <td colSpan={6}>
                                <StagedDetail
                                  row={r}
                                  busy={busy}
                                  onPreview={() => r.image && setPreview(r.image)}
                                  onUpload={(file) => uploadRow.mutate({ row: r.row, file })}
                                />
                              </td>
                            </tr>
                          )}
                        </Fragment>
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

      {preview && (
        <div
          className="dialog-backdrop"
          role="dialog"
          aria-label={preview}
          onClick={() => setPreview(null)}
        >
          <figure className="lightbox">
            <img src={imageUrl(preview)} alt={preview} />
            <figcaption className="mono">{preview}</figcaption>
          </figure>
        </div>
      )}
    </div>
  )
}

function StagedDetail({
  row,
  busy,
  onPreview,
  onUpload,
}: {
  row: StagedRow
  busy: boolean
  onPreview: () => void
  onUpload: (file: File) => void
}) {
  const pick = useRef<HTMLInputElement>(null)
  return (
    <div className="staged-detail">
      <input
        ref={pick}
        type="file"
        accept="image/*"
        hidden
        aria-label={`Upload an image for row ${row.row}`}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onUpload(file)
          e.target.value = ''
        }}
      />
      {row.image ? (
        <button type="button" className="staged-preview" onClick={onPreview}>
          <img src={imageUrl(row.image)} alt={row.image} />
        </button>
      ) : (
        <button
          className="dropzone staged-drop"
          onClick={() => pick.current?.click()}
          disabled={busy}
        >
          <div className="dropzone-title">Upload a matching image</div>
          <div className="dropzone-hint">Pairs with row {row.row} straight away</div>
        </button>
      )}
      <div>
        <div className="staged-detail-line">
          <span>Filed as</span>
          <span className="mono">{row.filename || '—'}</span>
        </div>
        <div className="staged-detail-line">
          <span>Paired with</span>
          <span className="mono">{row.image ?? 'no image'}</span>
        </div>
        {row.candidate_filenames.length > 0 && (
          <div className="staged-detail-line">
            <span>Candidates</span>
            <span className="mono">{row.candidate_filenames.join(', ')}</span>
          </div>
        )}
        {row.image && (
          <button
            className="btn btn-quiet btn-sm"
            style={{ marginTop: 10 }}
            onClick={() => pick.current?.click()}
            disabled={busy}
          >
            Replace image
          </button>
        )}
      </div>
    </div>
  )
}
