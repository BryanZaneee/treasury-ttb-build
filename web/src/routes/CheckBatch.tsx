import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, apiUrl, imageUrl } from '../api/client'
import type { Job, StagedBatch, StagedRow } from '../api/client'
import { PICK_LABEL, verdictSummary } from '../lib/copy'
import { useEscape } from '../lib/dialog'
import { waitForJob } from '../lib/job'
import { useToast } from '../lib/toast'
import { Lightbox } from '../components/Lightbox'
import { Dialog } from '../components/Dialog'

const BUCKET: Record<string, { label: string; pill: string }> = {
  matched: { label: 'Matched', pill: 'pill-match' },
  matched_fuzzy: { label: 'Matched · extension differs', pill: 'pill-review' },
  missing_image: { label: 'No image', pill: 'pill-pending' },
  ambiguous: { label: 'Ambiguous', pill: 'pill-fail' },
}

const REQUIRED =
  'filename, brand_name, class_type, alcohol_content, net_contents, producer, country_of_origin, government_warning, applicant'

/** The pointer at the staged batch; the batch itself lives on the server (§5.5). */
const BATCH_KEY = 'ttb.batch'

export function CheckBatch() {
  const [batchId, setBatchId] = useState(() => localStorage.getItem(BATCH_KEY) ?? '')
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  // The row whose image picker is open, and the selection the bulk bar acts on.
  const [picking, setPicking] = useState<StagedRow | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  // Set while a commit waits for the reviewer to accept that ambiguous rows drop.
  const [dropWarn, setDropWarn] = useState<{ rows: number[]; verify: boolean } | null>(null)
  const [clearing, setClearing] = useState(false)
  const csvRef = useRef<HTMLInputElement>(null)
  const imgRef = useRef<HTMLInputElement>(null)
  useEscape(() => {
    setPreview(null)
    setPicking(null)
    setClearing(false)
    setDropWarn(null)
  })
  const [csvName, setCsvName] = useState('No file selected')
  const [imgCount, setImgCount] = useState('No images selected')
  const [imgFiles, setImgFiles] = useState(0)

  // The pickers name what is about to be staged, so staging makes them stale.
  const resetPickers = () => {
    setCsvName('No file selected')
    setImgCount('No images selected')
    setImgFiles(0)
    if (csvRef.current) csvRef.current.value = ''
    if (imgRef.current) imgRef.current.value = ''
  }
  const client = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()

  const stagedBatch = useQuery({
    queryKey: ['batch', batchId],
    // The id can outlive the batch (a fixtures reset, a wiped store), so drop
    // the pointer rather than hold the page on a 404 nobody can act on.
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

  /** Put the batch down without filing it; nothing was ever written to the store. */
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

  // The image, not just the pairing: it stops being offered to every row.
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
      return waitForJob(started, setJob)
    },
    onSuccess: async (finished) => {
      setJob(finished)
      setSelected(new Set())
      client.invalidateQueries({ queryKey: ['records'] })
      reportJob(finished)
      // Re-read what is left rather than guess. A fully consumed batch answers
      // 404, which is the same outcome as an empty one, not an error.
      try {
        const left = await api<StagedBatch>(`/batches/${batchId}`)
        if (left.rows.length === 0) forget()
        else staged(left)
      } catch {
        forget()
      }
    },
    onError: (e) => setError(String(e)),
  })

  /** What the batch did, with the way into the queue it just filled. */
  const reportJob = (job: Job) => {
    const verdicts = verdictSummary(job.verdicts)
    toast({
      kind: job.failed > 0 ? 'warn' : 'success',
      title: `${job.committed} application${job.committed === 1 ? '' : 's'} filed`,
      body: (
        <>
          {verdicts ? (
            <>
              Verified {job.completed} of {job.total}.
              <div style={{ marginTop: 4 }}>{verdicts}</div>
            </>
          ) : (
            'Filed without verification. Run it from the inbox when you are ready.'
          )}
          {job.failed > 0 && (
            <div style={{ marginTop: 4 }}>
              {job.failed} could not be read and stayed unverified.
            </div>
          )}
        </>
      ),
      actions: [
        {
          label: 'Open the inbox',
          onClick: () => {
            navigate('/inbox')
          },
        },
        { label: 'Dismiss', tone: 'quiet', onClick: () => {} },
      ],
    })
  }

  /** File these rows, warning first about the ones that cannot be. PRD §5.5
      blocks on `ambiguous` alone; `missing_image` files and simply cannot be
      verified (acceptance test 9 - "1 files as image-missing, no row lost"). */
  const unresolved = (rows: number[]) =>
    (batch?.rows ?? []).filter((r) => rows.includes(r.row) && r.bucket === 'ambiguous')

  const fileRows = (rows: number[], verify: boolean) => {
    if (!batch || rows.length === 0) return
    if (unresolved(rows).length > 0) {
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
              /* ponytail: indeterminate on purpose - staging is one request with
                 no job to poll, so a percentage would be invented. */
              <div className="dropzone batch-empty" style={{ marginTop: 12, padding: 20 }}>
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
              <div className="dropzone batch-empty" style={{ marginTop: 12, padding: 20 }}>
                <div className="dropzone-hint" style={{ fontSize: 13.5 }}>
                  {batch ? 'Every staged row has been filed.' : 'No applications staged yet.'}
                  <br />
                  Upload a CSV above or load the bundled sample batch.
                </div>
              </div>
            ) : (
              <>
                {/* General, not per row: the Pairing column already says which. */}
                {unresolved(rowNumbers).length > 0 && (
                  <div className="banner banner-error" style={{ marginTop: 12, marginBottom: 0 }}>
                    <div className="banner-mark" aria-hidden="true">
                      !
                    </div>
                    <div className="banner-text">
                      More than one image matches these rows, so there is no single label to
                      file. See Pairing below. Rows with no image at all are not affected -
                      they file and can be verified once a label is added.
                    </div>
                  </div>
                )}
                {/* The one bucket that files silently while still being a guess,
                    so it says so once at the top of the table. */}
                {batch.summary.matched_fuzzy > 0 && (
                  <div className="banner" style={{ marginTop: 12, marginBottom: 0 }}>
                    <div className="banner-mark" aria-hidden="true">
                      i
                    </div>
                    <div className="banner-text">
                      {batch.summary.matched_fuzzy} row
                      {batch.summary.matched_fuzzy === 1 ? ' was' : 's were'} paired on the
                      filename alone, ignoring the extension. Check the image is the right one
                      and press Confirm, or pick another.
                    </div>
                  </div>
                )}
                {/* PRD §5.5's fifth bucket: the table has a row per application,
                    so an unclaimed image has nowhere else to appear. */}
                {batch.summary.unused_images.length > 0 && (
                  <div className="banner" style={{ marginTop: 12, marginBottom: 0 }}>
                    <div className="banner-mark" aria-hidden="true">
                      i
                    </div>
                    <div className="banner-text">
                      {batch.summary.unused_images.length} uploaded image
                      {batch.summary.unused_images.length === 1 ? '' : 's'} no row claims:{' '}
                      <span className="mono">{batch.summary.unused_images.join(', ')}</span>. Pick
                      one from a row&rsquo;s Pairing cell to use it.
                    </div>
                  </div>
                )}
                <div className="scroll-x" style={{ marginTop: 12 }}>
                  <table className="staged-table">
                    <thead>
                      {/* Replaces the header rather than sitting above it, and
                          scrolls with the columns it acts on. */}
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
                          <th className="staged-actions">Image</th>
                          <th />
                        </tr>
                      )}
                    </thead>
                    <tbody>
                      {batch.rows.map((r, index) => (
                        <StagedTableRow
                          key={r.row}
                          row={r}
                          position={index + 1}
                          busy={busy}
                          checked={selected.has(r.row)}
                          onSelect={() => toggleOne(r.row)}
                          onPreview={() => r.image && setPreview(r.image)}
                          onPick={() => setPicking(r)}
                          onConfirm={() => r.image && assign.mutate({ row: r.row, image: r.image })}
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
              disabled={!batch || batch.rows.length === 0 || commit.isPending}
            >
              {commit.isPending && <span className="spinner" />}
              {batch
                ? `File and verify ${committable} row${committable === 1 ? '' : 's'}`
                : 'File and verify batch'}
            </button>
            {commit.isPending && job && (
              <p className="card-note">
                {job.completed}/{job.total} verified…
              </p>
            )}
            {/* The staged batch outlives the page now, so there has to be a way
                to put it down that is not filing it. */}
            <button
              className="btn btn-danger btn-wide"
              style={{ marginTop: 10 }}
              onClick={() => setClearing(true)}
              disabled={!batch || commit.isPending}
            >
              Clear staged batch
            </button>
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
        <Lightbox
          src={imageUrl(preview)}
          alt={preview}
          caption={preview}
          onClose={() => setPreview(null)}
        />
      )}

      {picking && batch && (
        <ImagePicker
          row={picking}
          position={batch.rows.indexOf(picking) + 1}
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

      {clearing && batch && (
        <Dialog
          title="Clear the staged batch?"
          titleId="clear-title"
          onClose={() => setClearing(false)}
          footer={
            <>
              <button
                className="btn btn-danger"
                onClick={() => {
                  setClearing(false)
                  clearStaging()
                }}
              >
                Yes, clear it
              </button>
              <button className="btn btn-quiet" onClick={() => setClearing(false)}>
                Cancel
              </button>
            </>
          }
        >
          <p className="card-note">
            {batch.rows.length} staged row{batch.rows.length === 1 ? '' : 's'} and the pairing work
            done on them are discarded. Nothing has been filed yet, so nothing is removed from the
            store, but the CSV and its images have to be uploaded again.
          </p>
        </Dialog>
      )}

      {dropWarn && batch && (
        <Dialog
          title="Some rows match more than one image"
          titleId="drop-title"
          onClose={() => setDropWarn(null)}
          footer={
            <>
              <button
                className="btn"
                disabled={commit.isPending}
                onClick={() => {
                  const drop = unresolved(dropWarn.rows).map((r) => r.row)
                  const keep = dropWarn.rows.filter((n) => !drop.includes(n))
                  const verify = dropWarn.verify
                  setDropWarn(null)
                  dropRows
                    .mutateAsync(drop)
                    .then(() => {
                      if (keep.length > 0) commit.mutate({ rows: keep, verify })
                    })
                    .catch((e) => setError(String(e)))
                }}
              >
                Drop them and file the rest
              </button>
              <button className="btn btn-quiet push" onClick={() => setDropWarn(null)}>
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
              Two or more uploaded images normalise to the same filename, so there is no single
              label to file. These rows will be <strong>dropped, not filed</strong>. Pick a label
              for them first if you want to keep them.
            </div>
          </div>
          {unresolved(dropWarn.rows).map((r) => (
            <div className="staged-drop-row" key={r.row}>
              <span className="num">{batch.rows.indexOf(r) + 1}</span>
              <span>{r.applicant || r.brand || 'No applicant'}</span>
              <span>More than one match</span>
            </div>
          ))}
        </Dialog>
      )}
    </div>
  )
}

function StagedTableRow({
  row,
  position,
  busy,
  checked,
  onSelect,
  onPreview,
  onPick,
  onConfirm,
  onUpload,
  onDrop,
}: {
  row: StagedRow
  /* `row.row` keeps its number when rows above it are dropped - right for the
     API, wrong for a column headed #. */
  position: number
  busy: boolean
  checked: boolean
  onSelect: () => void
  onPreview: () => void
  onPick: () => void
  onConfirm: () => void
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
          aria-label={`Select row ${position}`}
          onChange={onSelect}
        />
      </td>
      <td className="num">{position}</td>
      <td>
        {/* Enlarges the specimen, or supplies one when the row has none. */}
        <button
          type="button"
          className="thumb"
          aria-label={
            row.image ? `Enlarge ${row.image}` : `Upload a label image for row ${position}`
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
          aria-label={`Upload an image for row ${position}`}
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
      <td className="staged-actions">
        <div className="row">
          {/* PRD §5.5 wants "visual confirmation before commit". Confirming
              re-sends the row's own image; assign treats that as `matched`. */}
          {row.bucket === 'matched_fuzzy' && (
            <button className="btn btn-quiet btn-sm" disabled={busy} onClick={onConfirm}>
              Confirm
            </button>
          )}
          <button className="btn btn-quiet btn-sm" disabled={busy} onClick={onPick}>
            {PICK_LABEL[row.bucket] ?? (row.image ? 'Change' : 'Attach')}
          </button>
        </div>
      </td>
      <td>
        <button
          type="button"
          className="cell-x"
          aria-label={`Remove row ${position} from this batch`}
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
 * Pair a staged row with an image: its own candidates, then anything unclaimed,
 * then a file off the machine. Also how an ambiguous row is settled - both
 * candidates are listed and the spare can be dropped here.
 */
function ImagePicker({
  row,
  position,
  unused,
  busy,
  onPick,
  onUpload,
  onDiscard,
  onClose,
}: {
  row: StagedRow
  position: number
  unused: string[]
  busy: boolean
  onPick: (name: string | null) => void
  onUpload: (file: File) => void
  onDiscard: (name: string) => void
  onClose: () => void
}) {
  const pick = useRef<HTMLInputElement>(null)
  // The uploads that made this row ambiguous lead under their own heading,
  // rather than mixed in with every other unclaimed file.
  const conflicting = row.bucket === 'ambiguous' ? row.candidate_filenames : []
  const others = [
    ...new Set([...(row.image ? [row.image] : []), ...row.candidate_filenames, ...unused]),
  ].filter((name) => !conflicting.includes(name))
  return (
    <Dialog
      title={`Image for row ${position}`}
      titleId="picker-title"
      wide
      onClose={onClose}
      subtitle={
        <p className="card-note">
          Filed as <span className="mono">{row.filename || 'no filename'}</span>
          {row.bucket === 'ambiguous' &&
            '. More than one upload matches this name, so pick the right one.'}
        </p>
      }
      footer={
        <>
          <input
            ref={pick}
            type="file"
            accept="image/*"
            hidden
            aria-label={`Upload an image for row ${position}`}
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
        </>
      }
    >
      {conflicting.length === 0 && others.length === 0 && (
        <p className="card-note">
          No unclaimed images are left in this batch. Upload the label instead.
        </p>
      )}
      {conflicting.length > 0 && (
        <>
          <div className="picker-group">
            {conflicting.length} uploads normalise to this row&rsquo;s filename. Pick the one
            that belongs to it, and remove the other with its × so it stops matching.
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
    </Dialog>
  )
}

/** Click to pair the row with it, × to drop the file from the batch. */
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
              aria-label={`Pair this row with ${name}`}
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
