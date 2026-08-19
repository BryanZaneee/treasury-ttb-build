import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, imageUrl } from '../api/client'
import type { RecordRow, SpecimenSummary } from '../api/client'
import { QUALITY_LABEL } from '../lib/copy'
import { useToast } from '../lib/toast'
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

/** S1/S2: file one application against a specimen, prefilled from a named sample. */
export function CheckLabel() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [application, setApplication] = useState({ ...BLANK })
  const [applicant, setApplicant] = useState('')
  const [specimen, setSpecimen] = useState('')
  const [error, setError] = useState<string | null>(null)

  const toast = useToast()
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ provider: string }>('/health'),
    staleTime: 60_000,
  })

  const specimens = useQuery({
    queryKey: ['specimens'],
    queryFn: () => api<SpecimenSummary[]>('/specimens'),
  })
  const named = (specimens.data ?? []).filter((s) => s.title)
  const chosen = specimens.data?.find((s) => s.filename === specimen)

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
      form.set('specimen_key', specimen)
      const record = await api<RecordRow>('/records', { method: 'POST', form })
      const verified = await api<RecordRow>(`/records/${record.id}/verify`, { method: 'POST' })
      return verified
    },
    onSuccess: (record) => {
      client.invalidateQueries({ queryKey: ['records'] })
      if (readByFallback(record, health.data?.provider)) {
        toast({ kind: 'warn', title: FALLBACK_TITLE, body: FALLBACK_BODY })
      }
      navigate(`/records/${record.id}`)
    },
    onError: (e) => setError(String(e)),
  })

  const set = (key: keyof typeof BLANK, value: string | boolean) =>
    setApplication((prev) => ({ ...prev, [key]: value }))

  const pick = (filename: string) => {
    setSpecimen(filename)
    prefill.mutate(filename)
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Step 1 of 2</div>
          <h1>Check one label</h1>
          <p className="lede">
            Select a label specimen, enter the application data as filed, and submit for
            verification. A new record is written to the review queue.
          </p>
        </div>
      </div>

      <div className="card card-pad">
        <div className="card-title">Label specimen · bundled test specimens</div>
        <p className="card-note">
          <strong>These are synthetic samples for testing, not real applications.</strong> The
          brands are fictional and no real trade dress is reproduced. Between them they cover
          clean artwork and the degraded captures agents receive in the field, and each one
          reproduces a documented verdict.
        </p>

        {specimen ? (
          <div className="row" style={{ margin: '14px 0', alignItems: 'flex-start' }}>
            <div
              style={{
                width: 150,
                border: '1px solid var(--rule)',
                background: '#faf7f0',
                flex: 'none',
              }}
            >
              <img
                src={imageUrl(specimen)}
                alt={`Specimen ${specimen}`}
                style={{ width: '100%', display: 'block' }}
              />
            </div>
            <div>
              <div className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
                {specimen}
              </div>
              <div className="row" style={{ gap: 8, marginTop: 8 }}>
                <span className="chip">{QUALITY_LABEL[chosen?.quality ?? ''] ?? 'Clean capture'}</span>
                <span className="chip">Expects {chosen?.expected_verdict}</span>
              </div>
              <button
                className="btn btn-quiet btn-sm"
                style={{ marginTop: 10 }}
                onClick={() => setSpecimen('')}
              >
                Choose a different specimen
              </button>
            </div>
          </div>
        ) : (
          <div className="dropzone" style={{ margin: '14px 0' }}>
            <div className="dropzone-title">Select a bundled test specimen</div>
            <div className="dropzone-hint">Synthetic samples · no specimen selected</div>
          </div>
        )}

        <div className="sample-grid">
          {named.map((s) => (
            <button
              key={s.filename}
              className="sample"
              aria-pressed={specimen === s.filename}
              onClick={() => pick(s.filename)}
            >
              <span className="sample-thumb">
                <img src={imageUrl(s.filename)} alt="" />
              </span>
              <span>
                <span className="sample-tag">Sample</span>
                <span className="sample-title">{s.title}</span>
                <span className="sample-hint">{s.hint}</span>
              </span>
            </button>
          ))}
        </div>
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
            {specimen
              ? `Specimen ${specimen} (${(QUALITY_LABEL[chosen?.quality ?? ''] ?? 'clean capture').toLowerCase()}). Results are filed to the review inbox and persisted to the record store.`
              : 'Select a specimen above to continue.'}
          </p>
          {error && (
            <div className="banner-error" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
          <div className="stack" style={{ gap: 10, marginTop: 14 }}>
            <button
              className="btn btn-wide"
              onClick={() => submit.mutate()}
              disabled={submit.isPending || !specimen || !application.brand}
            >
              {submit.isPending && <span className="spinner" />}
              Submit for verification
            </button>
            <button
              className="btn btn-quiet btn-wide"
              disabled={!specimen || prefill.isPending}
              onClick={() => specimen && prefill.mutate(specimen)}
            >
              Prefill from specimen sample data
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
