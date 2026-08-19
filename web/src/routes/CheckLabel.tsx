import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, imageUrl } from '../api/client'
import type { Health, RecordDetail, RecordRow, SpecimenSummary } from '../api/client'
import type { Toast } from '../lib/toast'
import { useToast } from '../lib/toast'
import { FIELD_LABEL, RESULT_COPY } from '../lib/copy'
import { PILL_TEXT, kindOf } from '../lib/verdict'
import { REVIEWER } from '../lib/session'
import { FALLBACK_BODY, FALLBACK_TITLE, readByFallback } from '../lib/fallback'

const BLANK = {
  brand: '',
  class_type: '',
  abv: '',
  net: '',
  producer: '',
  origin: '',
  warning: true,
}

const ACCEPTED = 'image/png,image/jpeg,image/webp'

/** A determination reads differently depending on what it says. */
const TOAST_KIND: Record<string, Toast['kind']> = {
  match: 'success',
  review: 'warn',
  fail: 'error',
  invalid: 'error',
  pending: 'info',
}

/**
 * S1/S2: file one application against one label.
 *
 * A specimen is either an uploaded file or a bundled sample, never both — the
 * API refuses a request carrying each, because the two resolve to different
 * images and a record that carries one and verifies the other is worse than an
 * error.
 */
export function CheckLabel() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const toast = useToast()

  const [application, setApplication] = useState({ ...BLANK })
  const [applicant, setApplicant] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string>('')
  const [sample, setSample] = useState('')
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<Health>('/health'),
    staleTime: 60_000,
  })

  const specimens = useQuery({
    queryKey: ['specimens'],
    queryFn: () => api<SpecimenSummary[]>('/specimens'),
  })
  const named = (specimens.data ?? []).filter((s) => s.title)

  const prefill = useMutation({
    mutationFn: (filename: string) =>
      api<{ app: Record<string, string>; applicant: string }>(
        `/specimens/${encodeURIComponent(filename)}`,
      ),
    onSuccess: (data) => {
      setApplication({
        brand: data.app.brand ?? '',
        class_type: data.app.classType ?? '',
        abv: data.app.abv ?? '',
        net: data.app.net ?? '',
        producer: data.app.producer ?? '',
        origin: data.app.origin ?? '',
        warning: Boolean(data.app.warning),
      })
      setApplicant(data.applicant)
    },
  })

  const takeFile = (chosen: File | undefined) => {
    if (!chosen) return
    setSample('')
    setFile(chosen)
    setError(null)
    // Revoke the previous object URL rather than leaking one per pick.
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old)
      return URL.createObjectURL(chosen)
    })
  }

  const takeSample = (filename: string) => {
    setSample(filename)
    setFile(null)
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old)
      return ''
    })
    if (filename) prefill.mutate(filename)
  }

  const clearImage = () => {
    setFile(null)
    setSample('')
    setPreview((old) => {
      if (old) URL.revokeObjectURL(old)
      return ''
    })
    if (fileRef.current) fileRef.current.value = ''
  }

  const decide = useMutation({
    mutationFn: ({ id, override }: { id: string; override: boolean }) =>
      api(`/records/${id}`, {
        method: 'PATCH',
        body: { decision: 'accepted', override, reviewer_name: REVIEWER.name },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['records'] }),
    onError: (e) => toast({ kind: 'error', title: 'Not accepted', body: String(e) }),
  })

  /**
   * Accepting a record that did not pass records an override against the
   * reviewer's name (PRD §5.1), so the toast names every disagreeing field
   * before it will do so — the same thing the determination view does, rather
   * than a one-click bypass of it. The server enforces the rule independently.
   */
  const confirmOverride = (record: RecordDetail) => {
    const disagreeing = record.field_results.filter((f) => f.verdict !== 'match')
    toast({
      kind: 'warn',
      title: 'This record did not pass',
      sticky: true,
      body: (
        <>
          Accepting it overrides {disagreeing.length} disagreeing field
          {disagreeing.length === 1 ? '' : 's'}
          {disagreeing.length > 0 &&
            `: ${disagreeing.map((f) => FIELD_LABEL[f.field_key] ?? f.field_key).join(', ')}`}
          . <strong>{REVIEWER.name}</strong>, the timestamp and the override flag are recorded.
        </>
      ),
      actions: [
        {
          label: 'Accept application anyway',
          onClick: () => {
            decide.mutate({ id: record.id, override: true })
          },
        },
        {
          label: 'Open record',
          tone: 'quiet',
          onClick: () => {
            navigate(`/records/${record.id}`)
          },
        },
        { label: 'Cancel', tone: 'quiet', onClick: () => {} },
      ],
    })
  }

  const reportVerdict = (record: RecordDetail) => {
    const kind = kindOf(record.result)
    toast({
      kind: TOAST_KIND[kind] ?? 'info',
      title: `${record.app_brand || record.filename} — ${PILL_TEXT[kind]}`,
      sticky: true,
      body: (
        <>
          {RESULT_COPY[kind]}
          <div style={{ marginTop: 6 }}>
            Filed to the review inbox as <span className="mono">{record.id}</span>.
          </div>
        </>
      ),
      actions: [
        {
          label: 'Accept application',
          onClick: () => {
            if (record.result === 'match') {
              decide.mutate({ id: record.id, override: false })
              return
            }
            confirmOverride(record)
            // The confirm replaces this toast rather than stacking on it.
          },
        },
        {
          label: 'Open record',
          tone: 'quiet',
          onClick: () => {
            navigate(`/records/${record.id}`)
          },
        },
        { label: 'Dismiss', tone: 'quiet', onClick: () => {} },
      ],
    })
  }

  const submit = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.set('applicant', applicant || 'Unnamed applicant')
      form.set('beverage', application.class_type || 'Unclassified')
      form.set(
        'application',
        JSON.stringify({
          ...application,
          producer: application.producer || null,
          origin: application.origin || null,
        }),
      )
      if (file) form.set('image', file)
      else form.set('specimen_key', sample)

      const record = await api<RecordRow>('/records', { method: 'POST', form })
      await api<RecordRow>(`/records/${record.id}/verify`, { method: 'POST' })
      // The detail, not the verify response: the toast names the disagreeing
      // fields before it will record an override, and those are in it.
      return api<RecordDetail>(`/records/${record.id}`)
    },
    onSuccess: (record) => {
      client.invalidateQueries({ queryKey: ['records'] })
      if (readByFallback(record, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
      reportVerdict(record)
      // Stay put and clear the form: filing labels one after another is the
      // job, and being thrown into the record after each one interrupts it.
      // The toast carries the verdict and a way in.
      setApplication({ ...BLANK })
      setApplicant('')
      clearImage()
    },
    onError: (e) => setError(String(e)),
  })

  const set = (key: keyof typeof BLANK, value: string | boolean) =>
    setApplication((prev) => ({ ...prev, [key]: value }))

  const source = file ? file.name : sample
  const shown = file ? preview : sample ? imageUrl(sample) : ''

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Step 1 of 2</div>
          <h1>Check one label</h1>
          <p className="lede">
            Upload a label image, enter the application data as filed, and submit for
            verification. A new record is written to the review queue.
          </p>
        </div>
      </div>

      <div className="card card-pad">
        <div className="card-title">Label image</div>

        {/* One fixed-height slot for both states. Picking a file used to swap a
            ~90px dropzone for a 200px preview and push the form below it down
            the page. */}
        <div className="specimen-slot">
          {shown ? (
            <div className="row" style={{ alignItems: 'center', height: '100%' }}>
              <div className="label-frame label-frame-sm">
                <img src={shown} alt={`Label image ${source}`} />
              </div>
              <div>
                <div className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
                  {source}
                </div>
                <p className="card-note">
                  {file ? 'Uploaded from this device.' : 'A sample label, for testing.'}
                </p>
                <button
                  className="btn btn-quiet btn-sm"
                  style={{ marginTop: 10 }}
                  onClick={clearImage}
                >
                  Choose a different image
                </button>
              </div>
            </div>
          ) : (
            <button
              className={`dropzone${dragging ? ' dragging' : ''}`}
              style={{ width: '100%', height: '100%' }}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                takeFile(e.dataTransfer.files?.[0])
              }}
            >
              <div className="dropzone-title">Drop a label image, or choose a file</div>
              <div className="dropzone-hint">PNG, JPEG or WebP · up to 12 MB</div>
            </button>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED}
          hidden
          onChange={(e) => takeFile(e.target.files?.[0])}
        />

        <label className="field" style={{ maxWidth: 460, marginBottom: 0 }}>
          <span className="field-label">Or use a sample label for testing</span>
          <select value={sample} onChange={(e) => takeSample(e.target.value)}>
            <option value="">No sample selected</option>
            {named.map((s) => (
              <option key={s.filename} value={s.filename}>
                {s.title} — {s.hint}
              </option>
            ))}
          </select>
          <span className="card-note">
            Synthetic labels with fictional brands. Each one reproduces a documented verdict, and
            picking one fills the form below with the application it was filed against.
          </span>
        </label>
      </div>

      <div className="split-right" style={{ marginTop: 16 }}>
        <div className="card card-pad">
          <div className="card-title">Application data as filed</div>
          <div style={{ marginTop: 12 }}>
            <label className="field">
              <span className="field-label">Applicant</span>
              <input
                type="text"
                value={applicant}
                onChange={(e) => setApplicant(e.target.value)}
                placeholder="Filing entity"
              />
            </label>
            <div className="grid-2">
              {(
                [
                  ['brand', 'Brand name', ''],
                  ['class_type', 'Class / type', ''],
                  ['abv', 'Alcohol content', ''],
                  ['net', 'Net contents', ''],
                  ['producer', 'Bottler / producer (optional)', 'Not declared'],
                  ['origin', 'Country of origin (optional)', 'Not declared'],
                ] as const
              ).map(([key, label, placeholder]) => (
                <label className="field" key={key}>
                  <span className="field-label">{label}</span>
                  <input
                    type="text"
                    value={application[key] as string}
                    placeholder={placeholder}
                    onChange={(e) => set(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
            <label className="check-row">
              <input
                type="checkbox"
                checked={application.warning}
                onChange={(e) => set('warning', e.target.checked)}
              />
              <span>Applicant declares the required government warning appears on the label</span>
            </label>
          </div>
        </div>

        <div className="card card-pad">
          <div className="card-title">Submit</div>
          <p className="card-note">
            {source
              ? `${source} will be verified and filed to the review inbox.`
              : 'Add a label image above to continue.'}
          </p>
          {error && (
            <div className="banner-error" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
          <button
            className="btn btn-wide"
            style={{ marginTop: 14 }}
            onClick={() => submit.mutate()}
            disabled={submit.isPending || !source || !application.brand}
          >
            {submit.isPending && <span className="spinner" />}
            Submit for verification
          </button>
        </div>
      </div>
    </div>
  )
}
