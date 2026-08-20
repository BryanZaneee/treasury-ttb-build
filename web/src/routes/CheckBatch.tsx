import { useRef, useState } from 'react'
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
  const [preview, setPreview] = useState<string | null>(null)
  // The row whose image picker is open, and the selection the bulk bar acts on.
  const [picking, setPicking] = useState<StagedRow | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  // Set while a commit is waiting on the reviewer to accept that rows without
  // a specimen will be dropped rather than filed.
  const [dropWarn, setDropWarn] = useState<{ rows: number[]; verify: boolean } | null>(null)
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

  const dropRows = useMutation({
    mutationFn: async (rows: number[]) => {
      let last: StagedBatch | null = null
      for (const row of rows) {
        last = await api<StagedBatch>(`/batches/${batch!.batch_id}/rows/${row}`, {
          method: 'DELETE',
        })
      }
      return last!
    },
    onSuccess: (data) => {
      setSelected(new Set())
      staged(data)
    },
    onError: (e) => setError(String(e)),
  })

  const commit = useMutation({
    mutationFn: async ({ rows, verify }: { rows: number[]; verify: boolean }) => {
      const started = await api<Job>('/jobs', {
        method: 'POST',
        body: {
          scope: 'batch',
          batch_id: batch!.batch_id,
          rows,
          verify_now: verify,
        },
      })
      let state = started
      while (state.state === 'running') {
        setJob(state)
        await new Promise((r) => setTimeout(r, 350))
        state = await api<Job>(`/jobs/${started.id}`)
      }
      return state
    },
    onSuccess: async (finished) => {
      setJob(finished)
      setSelected(new Set())
      client.invalidateQueries({ queryKey: ['records'] })
      // The filed rows are gone from the staged document; re-read what is left
      // rather than guessing at it client side.
      setBatch(await api<StagedBatch>(`/batches/${batch!.batch_id}`))
    },
    onError: (e) => setError(String(e)),
  })

  /** File these rows, first warning about any that have no specimen: those are
      dropped, not filed - a record with no label cannot ever be verified. */
  const fileRows = (rows: number[], verify: boolean) => {
    if (!batch || rows.length === 0) return
    const imageless = batch.rows.filter((r) => rows.includes(r.row) && !r.image)
    if (imageless.length > 0) {
      setDropWarn({ rows, verify })
      return
    }
    commit.mutate({ rows, verify })
  }

  const committable = batch ? batch.rows.filter((r) => r.bucket !== 'ambiguous').length : 0
  const rowNumbers = batch?.rows.map((r) => r.row) ?? []
  const allSelected = rowNumbers.length > 0 && rowNumbers.every((n) => selected.has(n))
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(rowNumbers))
  const toggleOne = (row: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(row)) next.delete(row)
      else next.add(row)
      return next
    })
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
            {!batch || batch.rows.length === 0 ? (
              <div className="dropzone batch-empty" style={{ marginTop: 12, padding: 40 }}>
                <div className="dropzone-hint" style={{ fontSize: 13.5 }}>
                  {batch ? 'Every staged row has been filed.' : 'No applications staged yet.'}
                  <br />
                  Upload a CSV above or load the bundled sample batch.
                </div>
              </div>
            ) : (
              <>
                {batch.blocks_commit && (
                  <div className="banner-error" style={{ marginTop: 12 }}>
                    Commit is blocked while any row is ambiguous. Two uploaded files normalise
                    to the same name — open the row's Image picker and choose the right one.
                  </div>
                )}
                {selected.size > 0 && (
                  <div className="bulkbar" style={{ marginTop: 12 }}>
                    <span className="bulkbar-count">{selected.size} selected</span>
                    <button
                      className="btn btn-quiet btn-sm"
                      disabled={busy}
                      onClick={() => fileRows([...selected], false)}
                    >
                      Accept upload
                    </button>
                    <button
                      className="btn btn-quiet btn-sm"
                      disabled={busy}
                      onClick={() => fileRows([...selected], true)}
                    >
                      Accept and verify
                    </button>
                    <button
                      className="btn btn-quiet btn-sm"
                      disabled={busy}
                      onClick={() => dropRows.mutate([...selected])}
                    >
                      Reject
                    </button>
                    <button
                      className="btn btn-quiet btn-sm push"
                      onClick={() => setSelected(new Set())}
                    >
                      Clear
                    </button>
                  </div>
                )}
                <div className="scroll-x" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: 34 }}>
                          <input
                            type="checkbox"
                            aria-label={allSelected ? 'Clear selection' : 'Select every row'}
                            checked={allSelected}
                            ref={(el) => {
                              if (el) el.indeterminate = selected.size > 0 && !allSelected
                            }}
                            onChange={toggleAll}
                          />
                        </th>
                        <th>#</th>
                        <th>Label</th>
                        <th>Brand</th>
                        <th>Applicant</th>
                        <th>Filename</th>
                        <th>Pairing</th>
                        <th>Image</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {batch.rows.map((r) => (
                        <StagedTableRow
                          key={r.row}
                          row={r}
                          busy={busy}
                          checked={selected.has(r.row)}
                          onSelect={() => toggleOne(r.row)}
                          onPreview={() => r.image && setPreview(r.image)}
                          onPick={() => setPicking(r)}
                          onUpload={(file) => uploadRow.mutate({ row: r.row, file })}
                          onDrop={() => dropRows.mutate([r.row])}
                        />
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
              onClick={() => fileRows(rowNumbers, verifyNow)}
              disabled={
                !batch || batch.rows.length === 0 || batch.blocks_commit || commit.isPending
              }
            >
              {commit.isPending && <span className="spinner" />}
              {batch
                ? `${verifyNow ? 'File and verify' : 'File'} ${committable} rows`
                : 'File and verify batch'}
            </button>
            {commit.isPending && job && (
              <p className="card-note">
                {job.completed}/{job.total} verified…
              </p>
            )}
            {commit.isSuccess && job && (
              <p className="card-note">
                Filed {job.committed} record{job.committed === 1 ? '' : 's'}
                {Object.keys(job.verdicts).length > 0
                  ? ` · verified ${job.completed}/${job.total} · ${Object.entries(job.verdicts)
                      .map(([k, v]) => `${v} ${k}`)
                      .join(' · ')}`
                  : ' · awaiting verification'}
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
          tabIndex={-1}
          autoFocus
          onClick={() => setPreview(null)}
          onKeyDown={(e) => e.key === 'Escape' && setPreview(null)}
        >
          <figure className="lightbox">
            <img src={imageUrl(preview)} alt={preview} />
            <figcaption className="mono">{preview}</figcaption>
          </figure>
        </div>
      )}

      {picking && batch && (
        <ImagePicker
          row={picking}
          unused={batch.summary.unused_images}
          busy={busy}
          onPick={(name) => {
            assign.mutate({ row: picking.row, image: name })
            setPicking(null)
          }}
          onUpload={(file) => {
            uploadRow.mutate({ row: picking.row, file })
            setPicking(null)
          }}
          onDiscard={(name) => discard.mutate(name)}
          onClose={() => setPicking(null)}
        />
      )}

      {dropWarn && batch && (
        <div className="dialog-backdrop" role="presentation" onClick={() => setDropWarn(null)}>
          <div
            className="dialog dialog-sm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="drop-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dialog-head">
              <h2 id="drop-title">Some rows have no label</h2>
            </div>
            <div className="dialog-body">
              <div className="banner">
                <div className="banner-mark" aria-hidden="true">
                  !
                </div>
                <div className="banner-text">
                  These rows will be <strong>dropped, not filed</strong>. A record with no
                  specimen can never be verified — attach a label first if you want to keep it.
                </div>
              </div>
              {batch.rows
                .filter((r) => dropWarn.rows.includes(r.row) && !r.image)
                .map((r) => (
                  <div className="staged-drop-row" key={r.row}>
                    <span className="num">{r.row}</span>
                    <span>{r.brand || r.applicant || '—'}</span>
                    <span className="mono">{r.filename || 'no filename'}</span>
                  </div>
                ))}
            </div>
            <div className="dialog-foot">
              <button
                className="btn"
                disabled={commit.isPending}
                onClick={() => {
                  const keep = batch.rows
                    .filter((r) => dropWarn.rows.includes(r.row) && r.image)
                    .map((r) => r.row)
                  const drop = dropWarn.rows.filter((n) => !keep.includes(n))
                  const verify = dropWarn.verify
                  setDropWarn(null)
                  dropRows.mutateAsync(drop).then(() => {
                    if (keep.length > 0) commit.mutate({ rows: keep, verify })
                  })
                }}
              >
                Drop them and file the rest
              </button>
              <button className="btn btn-quiet" onClick={() => setDropWarn(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StagedTableRow({
  row,
  busy,
  checked,
  onSelect,
  onPreview,
  onPick,
  onUpload,
  onDrop,
}: {
  row: StagedRow
  busy: boolean
  checked: boolean
  onSelect: () => void
  onPreview: () => void
  onPick: () => void
  onUpload: (file: File) => void
  onDrop: () => void
}) {
  const pick = useRef<HTMLInputElement>(null)
  return (
    <tr className={checked ? 'staged-selected' : undefined}>
      <td>
        <input
          type="checkbox"
          checked={checked}
          aria-label={`Select row ${row.row}`}
          onChange={onSelect}
        />
      </td>
      <td className="num">{row.row}</td>
      <td>
        {/* The thumbnail enlarges the specimen, as it does in the review inbox.
            With no specimen it is the shortest way to supply one. */}
        <button
          type="button"
          className="thumb"
          aria-label={
            row.image ? `Enlarge ${row.image}` : `Upload a label image for row ${row.row}`
          }
          onClick={() => (row.image ? onPreview() : pick.current?.click())}
        >
          {row.image ? (
            <img src={imageUrl(row.image)} alt="" />
          ) : (
            <span className="thumb-empty">none</span>
          )}
        </button>
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
      </td>
      <td>{row.brand}</td>
      <td>{row.applicant}</td>
      <td className="mono" style={{ fontSize: 12 }}>
        {row.filename}
      </td>
      <td>
        <span className={`pill pill-sm ${BUCKET[row.bucket].pill}`}>
          {BUCKET[row.bucket].label}
        </span>
        {row.errors.length > 0 && (
          <div style={{ fontSize: 11, color: 'var(--ink-5)', marginTop: 4 }}>
            {row.errors.join('; ')}
          </div>
        )}
      </td>
      <td>
        <button className="btn btn-quiet btn-sm" disabled={busy} onClick={onPick}>
          {row.image ? 'Change' : 'Attach'}
        </button>
      </td>
      <td>
        <button
          type="button"
          className="cell-x"
          aria-label={`Remove row ${row.row} from this batch`}
          disabled={busy}
          onClick={onDrop}
        >
          ×
        </button>
      </td>
    </tr>
  )
}

/**
 * Pair one staged row with an image: its own candidates first, then anything no
 * other row claimed, then a file off the reviewer's machine. This is also how
 * an ambiguous row is settled - two uploads normalising to one name are both
 * listed, and the spare can be dropped from the batch here.
 */
function ImagePicker({
  row,
  unused,
  busy,
  onPick,
  onUpload,
  onDiscard,
  onClose,
}: {
  row: StagedRow
  unused: string[]
  busy: boolean
  onPick: (name: string | null) => void
  onUpload: (file: File) => void
  onDiscard: (name: string) => void
  onClose: () => void
}) {
  const pick = useRef<HTMLInputElement>(null)
  const offered = [
    ...new Set([...(row.image ? [row.image] : []), ...row.candidate_filenames, ...unused]),
  ]
  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="picker-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-head">
          <h2 id="picker-title">Image for row {row.row}</h2>
          <p className="card-note">
            Filed as <span className="mono">{row.filename || 'no filename'}</span>
            {row.bucket === 'ambiguous' &&
              ' — more than one upload matches this name, so pick the right one.'}
          </p>
        </div>

        <div className="dialog-body">
          {offered.length === 0 ? (
            <p className="card-note">
              No unclaimed images are left in this batch. Upload the specimen instead.
            </p>
          ) : (
            <div className="unused-strip">
              {offered.map((name) => (
                <figure key={name}>
                  <span
                    className={`thumb thumb-lg${name === row.image ? ' thumb-current' : ''}`}
                  >
                    <button
                      type="button"
                      className="thumb-open"
                      aria-label={`Pair row ${row.row} with ${name}`}
                      disabled={busy}
                      onClick={() => onPick(name)}
                    >
                      <img src={imageUrl(name)} alt="" />
                    </button>
                    <button
                      type="button"
                      className="thumb-x"
                      aria-label={`Remove ${name} from this batch`}
                      disabled={busy}
                      onClick={() => onDiscard(name)}
                    >
                      ×
                    </button>
                  </span>
                  <figcaption className="mono">{name}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </div>

        <div className="dialog-foot">
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
          <button className="btn" disabled={busy} onClick={() => pick.current?.click()}>
            Upload a file
          </button>
          {row.image && (
            <button className="btn btn-quiet" disabled={busy} onClick={() => onPick(null)}>
              Unpair
            </button>
          )}
          <button className="btn btn-quiet push" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
