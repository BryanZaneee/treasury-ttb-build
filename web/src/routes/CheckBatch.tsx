import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

/** Where the staged batch id is remembered, so a reviewer can leave the page
    and come back to the batch they were working on. The batch itself lives on
    the server (PRD §5.5) - this is only the pointer at it. */
const BATCH_KEY = 'ttb.batch'

export function CheckBatch() {
  const [batchId, setBatchId] = useState(() => localStorage.getItem(BATCH_KEY) ?? '')
  const [job, setJob] = useState<Job | null>(null)
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
  const [imgFiles, setImgFiles] = useState(0)

  // The pickers name what is about to be staged, so they are stale the moment
  // it has been.
  const resetPickers = () => {
    setCsvName('No file selected')
    setImgCount('No images selected')
    setImgFiles(0)
    if (csvRef.current) csvRef.current.value = ''
    if (imgRef.current) imgRef.current.value = ''
  }
  const client = useQueryClient()

  const stagedBatch = useQuery({
    queryKey: ['batch', batchId],
    // The id can outlive the batch - a fixtures reset, or a restart of a store
    // that was wiped underneath it. Drop the pointer on the way past rather
    // than holding the page on a 404 the reviewer cannot act on.
    queryFn: async () => {
      try {
        return await api<StagedBatch>(`/batches/${batchId}`)
      } catch (e) {
        localStorage.removeItem(BATCH_KEY)
        throw e
      }
    },
    enabled: Boolean(batchId),
    retry: false,
  })
  const batch = stagedBatch.data ?? null

  const forget = () => {
    localStorage.removeItem(BATCH_KEY)
    setBatchId('')
  }

  /** Put the staged batch down without filing it, and empty the pickers with
      it. The batch stays on the server; nothing was ever written to the store. */
  const clearStaging = () => {
    forget()
    setSelected(new Set())
    setJob(null)
    setError(null)
    resetPickers()
  }

  const staged = (data: StagedBatch) => {
    localStorage.setItem(BATCH_KEY, data.batch_id)
    setBatchId(data.batch_id)
    client.setQueryData(['batch', data.batch_id], data)
    setError(null)
  }


  const loadSample = useMutation({
    mutationFn: () =>
      api<{ batch: StagedBatch }>('/fixtures', { method: 'POST', body: { mode: 'stage' } }),
    onSuccess: (data) => {
      staged(data.batch)
      setJob(null)
      resetPickers()
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
      resetPickers()
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
      const left = await api<StagedBatch>(`/batches/${batchId}`)
      if (left.rows.length === 0) forget()
      else staged(left)
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
  const blocking = batch?.rows.filter((r) => r.bucket === 'ambiguous') ?? []
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
  const staging = stage.isPending || loadSample.isPending

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
            <div className="card-title">Application CSV</div>
            <p className="card-note">Required columns: {REQUIRED}</p>
            <div className="grid-2" style={{ marginTop: 12 }}>
              <button
                className="dropzone"
                disabled={staging}
                onClick={() => csvRef.current?.click()}
              >
                <div className="dropzone-title">Choose CSV file</div>
                <div className="dropzone-hint">{csvName}</div>
              </button>
              <button
                className="dropzone"
                disabled={staging}
                onClick={() => imgRef.current?.click()}
              >
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
              onChange={(e) => {
                const count = e.target.files?.length ?? 0
                setImgFiles(count)
                setImgCount(count ? `${count} images selected` : 'No images selected')
              }}
            />
            <div className="row" style={{ marginTop: 12 }}>
              <button
                className="btn"
                onClick={() => stage.mutate()}
                disabled={staging}
              >
                {stage.isPending && <span className="spinner spinner-dark" />}
                {stage.isPending ? 'Staging…' : 'Stage upload'}
              </button>
            </div>
          </div>

        <div className="card card-pad area-step2">
            <div className="card-title">Staged applications</div>
            {error && (
              <div className="banner-error" style={{ marginTop: 12, marginBottom: 0 }}>
                {error}
              </div>
            )}
            {staging ? (
              /* ponytail: indeterminate on purpose. Staging is one request with
                 no server-side job to poll, unlike commit, so a percentage
                 would be invented. */
              <div className="dropzone batch-empty" style={{ marginTop: 12, padding: 40 }}>
                <div className="dropzone-hint" style={{ fontSize: 13.5 }}>
                  <span className="spinner spinner-dark" />{' '}
                  {stage.isPending
                    ? `Uploading the CSV and ${imgFiles} label image${imgFiles === 1 ? '' : 's'}…`
                    : 'Loading the bundled sample batch…'}
                  <br />
                  Nothing is written to the store until you file the batch.
                </div>
              </div>
            ) : !batch || batch.rows.length === 0 ? (
              <div className="dropzone batch-empty" style={{ marginTop: 12, padding: 40 }}>
                <div className="dropzone-hint" style={{ fontSize: 13.5 }}>
                  {batch ? 'Every staged row has been filed.' : 'No applications staged yet.'}
                  <br />
                  Upload a CSV above or load the bundled sample batch.
                </div>
              </div>
            ) : (
              <>
                {/* Names the rows, not the rule: "any row is ambiguous" leaves the
                    reviewer to find which one. */}
                {batch.blocks_commit && (
                  <div className="banner-error" style={{ marginTop: 12 }}>
                    <strong>
                      Upload is blocked by row{blocking.length === 1 ? '' : 's'}{' '}
                      {blocking.map((r) => r.row).join(', ')}.
                    </strong>{' '}
                    More than one uploaded file matches{' '}
                    {blocking.length === 1 ? 'that row' : 'each of those rows'}. Open the Image
                    picker and choose which one belongs to it.
                  </div>
                )}
                <div className="scroll-x" style={{ marginTop: 12 }}>
                  <table className="staged-table">
                    <thead>
                      {/* The bar replaces the header row rather than sitting
                          above it, so ticking a box does not push the table
                          down - and inside the table it scrolls with the
                          columns it acts on. */}
                      {selected.size > 0 ? (
                        <tr>
                          <th className="bulkbar-cell" colSpan={8}>
                            <div className="bulkbar">
                              <span className="bulkbar-check">
                                <input
                                  type="checkbox"
                                  aria-label={
                                    allSelected ? 'Clear selection' : 'Select every row'
                                  }
                                  checked={allSelected}
                                  ref={(el) => {
                                    if (el) el.indeterminate = selected.size > 0 && !allSelected
                                  }}
                                  onChange={toggleAll}
                                />
                              </span>
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
                          </th>
                        </tr>
                      ) : (
                        <tr>
                          <th>
                            <input
                              type="checkbox"
                              aria-label="Select every row"
                              checked={false}
                              onChange={toggleAll}
                            />
                          </th>
                          <th>#</th>
                          <th>Label</th>
                          <th>Applicant</th>
                          <th>Filename</th>
                          <th>Pairing</th>
                          <th>Image</th>
                          <th />
                        </tr>
                      )}
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
            <div className="card-title">Run</div>
            {/* Filing the whole batch verifies it. Filing without verifying is
                a per-selection choice, and lives in the bar on the table. */}
            <button
              className="btn btn-wide"
              style={{ marginTop: 12 }}
              onClick={() => fileRows(rowNumbers, true)}
              disabled={
                !batch || batch.rows.length === 0 || batch.blocks_commit || commit.isPending
              }
            >
              {commit.isPending && <span className="spinner" />}
              {batch ? `File and verify ${committable} rows` : 'File and verify batch'}
            </button>
            {commit.isPending && job && (
              <p className="card-note">
                {job.completed}/{job.total} verified…
              </p>
            )}
            {/* The staged batch outlives the page now, so there has to be a way
                to put it down that is not filing it. */}
            {batch && batch.summary.unused_images.length > 0 && (
              <p className="card-note">
                {batch.summary.unused_images.length} uploaded image
                {batch.summary.unused_images.length === 1 ? '' : 's'} no row claims — pair one
                from any row's Image picker.
              </p>
            )}
            <button
              className="btn btn-quiet btn-wide"
              style={{ marginTop: 10 }}
              onClick={clearStaging}
              disabled={!batch || commit.isPending}
            >
              Clear staged batch
            </button>
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
              Start from a blank template with the columns above, or load a bundled sample batch
              of 25 applications with matching label images.
            </p>
            <a
              className="btn btn-quiet btn-wide"
              style={{ marginTop: 12 }}
              href={apiUrl('/export/template.csv')}
              download
            >
              Download blank template
            </a>
            <button
              className="btn btn-quiet btn-wide"
              style={{ marginTop: 10 }}
              onClick={() => loadSample.mutate()}
              disabled={staging}
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
                  label can never be verified — attach one first if you want to keep it.
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
              {/* PRD §5.5 files a row with no specimen - it just cannot be
                  verified. Dropping is the default because a record nobody can
                  ever verify is usually a mistake, not the intent. */}
              <button
                className="btn btn-quiet"
                disabled={commit.isPending}
                onClick={() => {
                  const { rows, verify } = dropWarn
                  setDropWarn(null)
                  commit.mutate({ rows, verify })
                }}
              >
                File them without a label
              </button>
              <button className="btn btn-quiet push" onClick={() => setDropWarn(null)}>
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
  // The uploads that made this row ambiguous are the answer to the question the
  // reviewer opened this dialog with, so they lead, under their own heading,
  // rather than being mixed in with every other unclaimed file.
  const conflicting = row.bucket === 'ambiguous' ? row.candidate_filenames : []
  const others = [
    ...new Set([...(row.image ? [row.image] : []), ...row.candidate_filenames, ...unused]),
  ].filter((name) => !conflicting.includes(name))
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
          {conflicting.length === 0 && others.length === 0 && (
            <p className="card-note">
              No unclaimed images are left in this batch. Upload the label instead.
            </p>
          )}
          {conflicting.length > 0 && (
            <>
              <div className="picker-group">
                {conflicting.length} uploads normalise to this row&rsquo;s filename. Pick the one
                that belongs to it — and remove the other with its × so it stops matching.
              </div>
              <ImageChoices
                names={conflicting}
                row={row}
                busy={busy}
                onPick={onPick}
                onDiscard={onDiscard}
              />
            </>
          )}
          {others.length > 0 && (
            <>
              {conflicting.length > 0 && (
                <div className="picker-group">Other unclaimed uploads</div>
              )}
              <ImageChoices
                names={others}
                row={row}
                busy={busy}
                onPick={onPick}
                onDiscard={onDiscard}
              />
            </>
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

/** The thumbnails one group of the picker offers: click to pair the row with
    it, × to drop the file from the batch entirely. */
function ImageChoices({
  names,
  row,
  busy,
  onPick,
  onDiscard,
}: {
  names: string[]
  row: StagedRow
  busy: boolean
  onPick: (name: string | null) => void
  onDiscard: (name: string) => void
}) {
  return (
    <div className="unused-strip">
      {names.map((name) => (
        <figure key={name}>
          <span className={`thumb thumb-lg${name === row.image ? ' thumb-current' : ''}`}>
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
  )
}
