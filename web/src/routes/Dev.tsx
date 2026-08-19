import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { BenchResponse, SpecimenSummary } from '../api/client'
import { Pill } from '../components/Pill'
import { FIELD_LABEL, QUALITY_LABEL } from '../lib/copy'

/**
 * Temporary developer page — the interactive form of scripts/bench.py (PRD §5.4).
 * Runs one specimen through several readers in the same process and reports what
 * each saw, how long it took, and how it scored against the fixture ground truth.
 *
 * Remove before the M6 cutover, along with routers/dev.py.
 */

type LaneConfig = { id: number; provider: string; model: string; effort: string; on: boolean }

const DEFAULT_LANES: LaneConfig[] = [
  { id: 1, provider: 'fake', model: '', effort: '', on: true },
  { id: 2, provider: 'ocr', model: '', effort: '', on: true },
  { id: 3, provider: 'openai', model: 'gpt-4.1-mini', effort: 'low', on: false },
]

const EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']

const FIELD_ORDER = ['brand', 'classType', 'abv', 'net', 'producer', 'origin', 'warning']

const laneKey = (lane: { provider: string; model: string | null }) =>
  `${lane.provider}${lane.model ? `/${lane.model}` : ''}`

function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)]
}

export function Dev() {
  const [specimen, setSpecimen] = useState('old-tom-pass.png')
  const [lanes, setLanes] = useState(DEFAULT_LANES)
  const [runs, setRuns] = useState(1)
  const [result, setResult] = useState<BenchResponse | null>(null)
  const [timings, setTimings] = useState<Record<string, number[]>>({})

  const specimens = useQuery({
    queryKey: ['specimens'],
    queryFn: () => api<SpecimenSummary[]>('/dev/specimens'),
  })

  const bench = useMutation({
    mutationFn: async () => {
      const active = lanes.filter((l) => l.on)
      const collected: Record<string, number[]> = {}
      let last: BenchResponse | null = null
      // One lane at a time, sequentially: concurrent runs measure throughput,
      // not latency, and the two are different questions (PRD §5.4).
      for (let run = 0; run < runs; run++) {
        last = await api<BenchResponse>('/dev/bench', {
          method: 'POST',
          body: {
            specimen,
            lanes: active.map((l) => ({
              provider: l.provider,
              model: l.model || null,
              effort: l.effort || null,
            })),
          },
        })
        for (const lane of last.lanes) {
          if (lane.total_ms != null) (collected[laneKey(lane)] ??= []).push(lane.total_ms)
        }
      }
      setTimings(collected)
      return last!
    },
    onSuccess: setResult,
  })

  const openaiModels = useQuery({
    queryKey: ['models', 'openai'],
    queryFn: () => api<string[]>('/dev/models?provider=openai'),
    retry: false,
  })
  const modelsFor = (provider: string) =>
    provider === 'openai' ? (openaiModels.data ?? []) : []

  const chosen = specimens.data?.find((s) => s.filename === specimen)
  const update = (id: number, patch: Partial<LaneConfig>) =>
    setLanes((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)))

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="eyebrow">Development · not part of the reviewer workflow</div>
          <h1>Reader bake-off</h1>
          <p className="lede">
            Race the readers against one specimen. Every reader sees the identical prepared
            image, so a difference below is the reader’s and not the preprocessing’s. Ground
            truth is <span className="mono">fixtures/expectations.json</span>.
          </p>
        </div>
        <div className="page-aside">
          Vision lanes call a paid provider on every run.
          <br />
          <span className="mono">remove before M6 cutover</span>
        </div>
      </div>

      <div className="split-right">
        <div className="card card-pad">
          <div className="card-title">Readers</div>
          <div className="scroll-x" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Effort</th>
                </tr>
              </thead>
              <tbody>
                {lanes.map((lane) => {
                  const local = lane.provider === 'fake' || lane.provider === 'ocr'
                  return (
                    <tr key={lane.id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`run ${lane.provider}`}
                          checked={lane.on}
                          onChange={(e) => update(lane.id, { on: e.target.checked })}
                        />
                      </td>
                      <td className="mono" style={{ fontWeight: 600 }}>
                        {lane.provider}
                      </td>
                      <td>
                        {local ? (
                          <input type="text" value="" placeholder="n/a" disabled />
                        ) : (
                          <select
                            value={lane.model}
                            onChange={(e) => update(lane.id, { model: e.target.value })}
                          >
                            {modelsFor(lane.provider).length === 0 && (
                              <option value={lane.model}>{lane.model}</option>
                            )}
                            {modelsFor(lane.provider).map((m) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td style={{ width: 130 }}>
                        {local ? (
                          <input type="text" value="" placeholder="n/a" disabled />
                        ) : (
                          <select
                            value={lane.effort}
                            onChange={(e) => update(lane.id, { effort: e.target.value })}
                          >
                            {EFFORTS.map((x) => (
                              <option key={x} value={x}>
                                {x}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card card-pad">
          <div className="card-title">Specimen</div>
          <label className="field" style={{ marginTop: 12 }}>
            <span className="field-label">Bundled specimen</span>
            <select value={specimen} onChange={(e) => setSpecimen(e.target.value)}>
              {specimens.data?.map((s) => (
                <option key={s.filename} value={s.filename}>
                  {s.filename} — expects {s.expected_verdict}
                </option>
              ))}
            </select>
          </label>
          {chosen && (
            <div className="row" style={{ gap: 8, marginBottom: 12 }}>
              <span className="chip">{QUALITY_LABEL[chosen.quality] ?? chosen.quality}</span>
              <span className="chip">Expects {chosen.expected_verdict}</span>
            </div>
          )}
          <label className="field">
            <span className="field-label">Runs per reader (median reported)</span>
            <input
              type="number"
              min={1}
              max={10}
              value={runs}
              onChange={(e) => setRuns(Math.max(1, Math.min(10, Number(e.target.value))))}
            />
          </label>
          <button
            className="btn btn-wide"
            onClick={() => bench.mutate()}
            disabled={bench.isPending || !lanes.some((l) => l.on)}
          >
            {bench.isPending && <span className="spinner" />}
            Run bench
          </button>
          {result?.sharpness != null && (
            <p className="card-note mono">
              prepared-image sharpness {result.sharpness.toFixed(1)}
            </p>
          )}
          {bench.isError && <div className="banner-error" style={{ marginTop: 12 }}>{String(bench.error)}</div>}
        </div>
      </div>

      {result && <Results result={result} timings={timings} runs={runs} />}
    </div>
  )
}

function Results({
  result,
  timings,
  runs,
}: {
  result: BenchResponse
  timings: Record<string, number[]>
  runs: number
}) {
  const ok = result.lanes.filter((l) => l.ok)
  return (
    <>
      <div className="card" style={{ marginTop: 20 }}>
        <div className="card-pad" style={{ borderBottom: '1px solid var(--rule)' }}>
          <div className="card-title">Speed and accuracy</div>
          <p className="card-note">
            {result.specimen} · expected verdict <strong>{result.expected_verdict}</strong> ·{' '}
            {runs} run{runs > 1 ? 's' : ''} per reader
          </p>
        </div>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Reader</th>
                <th>Verdict</th>
                <th>Quality read</th>
                <th>Fields correct</th>
                <th>Reader ms</th>
                <th>Rules ms</th>
                <th>Total ms</th>
                <th>Median ms</th>
                <th>Tokens in/out</th>
              </tr>
            </thead>
            <tbody>
              {result.lanes.map((lane) => {
                const key = laneKey(lane)
                return (
                  <tr key={key}>
                    <td className="mono" style={{ fontWeight: 600 }}>
                      {key}
                      {lane.effort ? ` · ${lane.effort}` : ''}
                    </td>
                    <td>
                      {lane.ok ? (
                        <>
                          <Pill verdict={lane.verdict} small />
                          {lane.verdict !== result.expected_verdict && (
                            <div style={{ fontSize: 11, color: 'var(--ink-5)', marginTop: 4 }}>
                              expected {result.expected_verdict}
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="pill pill-fail pill-sm">reader failed</span>
                      )}
                    </td>
                    <td className="mono">{lane.quality ?? '—'}</td>
                    <td className="num">
                      {lane.fields_correct != null
                        ? `${lane.fields_correct}/${lane.fields_total}`
                        : '—'}
                    </td>
                    <td className="num">{lane.reader_ms ?? '—'}</td>
                    <td className="num">{lane.rules_ms ?? '—'}</td>
                    <td className="num">{lane.total_ms ?? '—'}</td>
                    <td className="num">{median(timings[key] ?? []) ?? '—'}</td>
                    <td className="num">
                      {lane.input_tokens != null
                        ? `${lane.input_tokens}/${lane.output_tokens}`
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {result.lanes.some((l) => !l.ok) && (
          <div className="card-pad">
            {result.lanes
              .filter((l) => !l.ok)
              .map((l) => (
                <div className="banner-error" style={{ marginBottom: 8 }} key={laneKey(l)}>
                  <strong>{laneKey(l)}</strong>: {l.error}
                </div>
              ))}
          </div>
        )}
      </div>

      {ok.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-pad" style={{ borderBottom: '1px solid var(--rule)' }}>
            <div className="card-title">What each reader saw</div>
          </div>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Application says</th>
                  <th>Expected</th>
                  {ok.map((l) => (
                    <th key={laneKey(l)}>{laneKey(l)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FIELD_ORDER.map((key) => {
                  const row = ok[0]?.fields.find((f) => f.field_key === key)
                  if (!row) return null
                  return (
                    <tr key={key}>
                      <td style={{ fontWeight: 600 }}>{FIELD_LABEL[key] ?? key}</td>
                      <td>{row.app_value ?? '—'}</td>
                      <td>
                        <Pill verdict={row.expected ?? null} small />
                      </td>
                      {ok.map((lane) => {
                        const cell = lane.fields.find((f) => f.field_key === key)
                        const wrong = cell && cell.expected && cell.verdict !== cell.expected
                        return (
                          <td key={laneKey(lane)}>
                            <Pill verdict={cell?.verdict ?? null} small />
                            {wrong && (
                              <div style={{ fontSize: 11, color: 'var(--fail-fg)', marginTop: 3 }}>
                                ≠ expected
                              </div>
                            )}
                            <div className="mono" style={{ fontSize: 11.5, marginTop: 4 }}>
                              {cell?.label_value ?? '—'}
                            </div>
                            {cell?.confidence != null && (
                              <div style={{ fontSize: 11, color: 'var(--ink-6)' }}>
                                conf {cell.confidence.toFixed(2)}
                              </div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
