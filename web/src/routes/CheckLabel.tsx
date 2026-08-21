import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, imageUrl } from '../api/client'
import type { Health, RecordDetail, RecordRow, SpecimenSummary } from '../api/client'
import type { Toast } from '../lib/toast'
import { useEscape } from '../lib/dialog'
import { useToast } from '../lib/toast'
import { Lightbox } from '../components/Lightbox'
import {
  FALLBACK_BODY,
  FALLBACK_TITLE,
  FIELD_LABEL,
  PILL_TEXT,
  RESULT_COPY,
  contestedAccept,
  kindOf,
  readByFallback,
} from '../lib/copy'
import { REVIEWER } from '../lib/session'

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

/** A part-typed application survives a reload. The image rides along as a data
    URL when it is small enough - a 12 MB photo is not worth the typed fields. */
const DRAFT_KEY = 'ttb.label-draft'
const DRAFT_IMAGE_LIMIT = 2_000_000

type Draft = {
  application: typeof BLANK
  sample: string
  filename: string
  preview: string
}

function readDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch {
    return null
  }
}

function writeDraft(draft: Draft): void {
  // Drop the image rather than the draft; a quota error must not reach a keystroke.
  const slim = draft.preview.length > DRAFT_IMAGE_LIMIT ? { ...draft, preview: '' } : draft
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(slim))
  } catch {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...slim, preview: '' }))
    } catch {
      /* storage is unavailable; the draft is simply not kept */
    }
  }
}

/** A reload restores the picture, not the File; this rebuilds one so it submits. */
function fileFromDataUrl(dataUrl: string, name: string): File | null {
  const [head, body] = dataUrl.split(',')
  if (!head || !body) return null
  const type = head.match(/^data:([^;]+)/)?.[1] ?? 'image/jpeg'
  const bytes = Uint8Array.from(atob(body), (c) => c.charCodeAt(0))
  return new File([bytes], name, { type })
}

/** A determination reads differently depending on what it says. */
const TOAST_KIND: Record<string, Toast['kind']> = {
  match: 'success',
  review: 'warn',
  fail: 'error',
  invalid: 'error',
  pending: 'info',
}

/**
 * S1/S2: file one application against one label. The specimen is an upload or a
 * bundled sample, never both - a record carrying one and verifying the other is
 * worse than the error the API raises instead.
 */
export function CheckLabel() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const toast = useToast()

  const [saved] = useState(readDraft)
  const [application, setApplication] = useState(() => saved?.application ?? { ...BLANK })
  const [file, setFile] = useState<File | null>(() =>
    saved?.preview && saved.filename ? fileFromDataUrl(saved.preview, saved.filename) : null,
  )
  const [preview, setPreview] = useState<string>(() => saved?.preview ?? '')
  const [sample, setSample] = useState(() => saved?.sample ?? '')
  const [dragging, setDragging] = useState(false)
  const [zoomed, setZoomed] = useState(false)
  useEscape(() => setZoomed(false))
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
      api<{ app: Record<string, string> }>(`/specimens/${encodeURIComponent(filename)}`),
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
    },
  })

  // A data URL, not createObjectURL: the CSP allows `data:` and not `blob:`, so
  // an object URL renders in dev and is blocked in production. Also a string,
  // which is what lets the draft keep it.
  const takeFile = (chosen: File | undefined) => {
    if (!chosen) return
    setSample('')
    setFile(chosen)
    setError(null)
    const reader = new FileReader()
    reader.onload = () => setPreview(String(reader.result ?? ''))
    reader.onerror = () => setError('That image could not be read. Try another file.')
    reader.readAsDataURL(chosen)
  }

  const takeSample = (filename: string) => {
    setSample(filename)
    setFile(null)
    setPreview('')
    if (fileRef.current) fileRef.current.value = ''
    if (filename) prefill.mutate(filename)
  }

  const clearImage = () => {
    setFile(null)
    setSample('')
    setPreview('')
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
   * Accepting a record that did not pass records an override (PRD §5.1), so the
   * toast names every disagreeing field first rather than being a one-click
   * bypass of the determination view. The server enforces the rule anyway.
   */
  const confirmOverride = (record: RecordDetail) => {
    const disagreeing = record.field_results.filter((f) => f.verdict !== 'match')
    toast({
      kind: 'warn',
      title: 'This record did not pass',
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
      title: `${record.app_brand || record.filename}: ${PILL_TEXT[kind]}`,
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
            if (!contestedAccept(record.result)) {
              // The override is still recorded for anything short of a match
              // (PRD §5.1); it is only the challenge that a presentation
              // difference does not warrant.
              decide.mutate({ id: record.id, override: record.result !== 'match' })
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

  /** Poll until the server has adjudicated, then return the full detail. */
  const waitForVerdict = async (id: string): Promise<RecordDetail> => {
    for (let attempt = 0; attempt < 60; attempt++) {
      const detail = await api<RecordDetail>(`/records/${id}`)
      if (detail.verified) return detail
      await new Promise((r) => setTimeout(r, 300))
    }
    // Still pending after 18s: the record exists and the inbox will show it.
    return api<RecordDetail>(`/records/${id}`)
  }

  const submit = useMutation({
    mutationFn: async () => {
      const form = new FormData()
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
      // One request: as two, moving on between them stranded the record.
      form.set('verify_now', 'true')

      const record = await api<RecordRow>('/records', { method: 'POST', form })
      // Already running server-side; this waits only so the toast can name the
      // fields. Navigating away abandons the wait, not the verification.
      return waitForVerdict(record.id)
    },
    onSuccess: (record) => {
      client.invalidateQueries({ queryKey: ['records'] })
      if (readByFallback(record, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
      reportVerdict(record)
      // Stay put and clear: filing one after another is the job, and the toast
      // already carries the verdict and a way in.
      setApplication({ ...BLANK })
      clearImage()
      localStorage.removeItem(DRAFT_KEY)
    },
    onError: (e) => setError(String(e)),
  })

  const set = (key: keyof typeof BLANK, value: string | boolean) =>
    setApplication((prev) => ({ ...prev, [key]: value }))

  const source = file ? file.name : sample

  // On every change, not on unmount: closing the tab unmounts nothing.
  useEffect(() => {
    writeDraft({ application, sample, filename: file?.name ?? '', preview })
  }, [application, sample, file, preview])

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

      <input
        ref={fileRef}
        type="file"
        accept={ACCEPTED}
        hidden
        onChange={(e) => {
          takeFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />

      <div className="split-right" style={{ marginTop: 16 }}>
        <div className="card card-pad">
          <div className="card-title">Application data as filed</div>
          <div style={{ marginTop: 12 }}>
            <div className="grid-2">
              {(
                [
                  // Placeholders, not values: the shape each field is expected in.
                  ['brand', 'Brand name', 'Harbor Mist'],
                  ['class_type', 'Class / type', 'India Pale Ale'],
                  ['abv', 'Alcohol content', '6.8% Alc./Vol.'],
                  ['net', 'Net contents', '12 FL OZ'],
                  ['producer', 'Bottler / producer (optional)', 'Harbor Mist Brewing, Portland, OR'],
                  ['origin', 'Country of origin (optional)', 'United States'],
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
            {error && (
              <div className="banner-error" style={{ marginTop: 14 }}>
                {error}
              </div>
            )}
            <button
              className="btn btn-wide"
              style={{ marginTop: 16 }}
              onClick={() => submit.mutate()}
              disabled={submit.isPending || !source || !application.brand}
            >
              {submit.isPending && <span className="spinner" />}
              Submit for verification
            </button>
            <p className="card-note">
              {source
                ? `${source} will be verified and filed to the review inbox.`
                : 'Add a label image to continue.'}
            </p>
          </div>
        </div>

        {/* Always beside the form: a panel that appears once an image is chosen
            moves the form out from under the cursor. */}
        <div className="card card-pad specimen-side">
          <div className="card-title">Label image</div>
          {shown ? (
            <>
              <button
                className="label-frame label-frame-zoom"
                onClick={() => setZoomed(true)}
                aria-label={`Enlarge ${source}`}
              >
                <img src={shown} alt={`Label image ${source}`} />
              </button>
              <div className="mono" style={{ fontSize: 12.5, fontWeight: 600, marginTop: 10 }}>
                {source}
              </div>
              <p className="card-note">
                {file ? 'Uploaded from this device.' : 'A sample label, for testing.'}
              </p>
              <button className="btn btn-quiet btn-sm" onClick={clearImage}>
                Choose a different image
              </button>
            </>
          ) : (
            <>
              <button
                className={`dropzone${dragging ? ' dragging' : ''}`}
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
              <label className="field" style={{ marginTop: 14, marginBottom: 0 }}>
                <span className="field-label">Or use a sample label</span>
                <select value={sample} onChange={(e) => takeSample(e.target.value)}>
                  <option value="">No sample selected</option>
                  {named.map((s) => (
                    <option key={s.filename} value={s.filename}>
                      {s.brand} — {s.title}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </div>
      </div>

      {zoomed && shown && (
        <Lightbox
          src={shown}
          alt={`Label image ${source}`}
          caption={source}
          onClose={() => setZoomed(false)}
        />
      )}
    </div>
  )
}
