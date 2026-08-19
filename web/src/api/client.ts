/**
 * API client. One place that knows the base URL and the shared access token,
 * so no component has to think about either.
 *
 * PRD §8: there are no user accounts. Mutating endpoints take a shared bearer
 * token. In production a reviewer supplies it; for local dev it comes from
 * VITE_ACCESS_TOKEN. The *reader* API key never reaches the browser.
 */

/**
 * The app is served under PUBLIC_BASE_PATH in production (`/ttb-build`) and at
 * the root in dev. `import.meta.env.BASE_URL` mirrors Vite `base`, which is
 * driven by that same variable — so every URL the app builds must go through
 * here rather than starting with a bare `/api`, which would escape the subpath
 * and hit whatever else is mounted at the domain root.
 */
const ROOT = import.meta.env.BASE_URL.replace(/\/$/, '')
const BASE = `${ROOT}/api`

/** Absolute URL for an API path, base-path aware. */
export const apiUrl = (path: string) => `${BASE}${path}`

/** Absolute URL for a stored specimen image. */
export const imageUrl = (name: string) => `${BASE}/images/${encodeURIComponent(name)}`
const ACCESS_TOKEN = import.meta.env.VITE_ACCESS_TOKEN ?? ''
const ADMIN_TOKEN = import.meta.env.VITE_ADMIN_TOKEN ?? ''

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

type Options = {
  method?: string
  body?: unknown
  admin?: boolean
  form?: FormData
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = 'GET', body, admin = false, form } = options
  const headers: Record<string, string> = {}
  const token = admin ? ADMIN_TOKEN : ACCESS_TOKEN
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
  })

  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      detail = (await response.json()).detail
    } catch {
      // A non-JSON error body is still an error; keep the status text.
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export type Verdict = 'match' | 'review' | 'fail'

export type RecordRow = {
  id: string
  received: string
  applicant: string
  beverage: string
  filename: string
  specimen: string
  quality: string | null
  app_brand: string
  app_class_type: string
  app_alcohol_content: string
  app_net_contents: string
  app_producer: string | null
  app_origin: string | null
  app_warning_declared: boolean
  verified: boolean
  result: Verdict | null
  elapsed_ms: number | null
  engine: string | null
  decision: 'accepted' | 'returned' | null
  decided_by: string | null
  decided_at: string | null
  note: string | null
  override: boolean
  prep_ms: number | null
  reader_ms: number | null
  rules_ms: number | null
  reader_provider: string | null
  reader_model: string | null
}

export type FieldResult = {
  field_key: string
  app_value: string | null
  label_value: string | null
  verdict: Verdict | null
  note: string | null
  confidence: number | null
}

export type RecordDetail = RecordRow & { field_results: FieldResult[] }

export type Counts = {
  attention: number
  pending: number
  review: number
  fail: number
  closed: number
}

export type RecordsPage = { records: RecordRow[]; counts: Counts; cursor: string | null }

export type LaneResult = {
  provider: string
  model: string | null
  effort: string | null
  ok: boolean
  error: string | null
  reader_ms: number | null
  rules_ms: number | null
  total_ms: number | null
  verdict: Verdict | null
  quality: string | null
  fields_correct: number | null
  fields_total: number | null
  input_tokens: number | null
  output_tokens: number | null
  fields: {
    field_key: string
    app_value: string | null
    label_value: string | null
    verdict: Verdict | null
    expected: Verdict | null
    note: string | null
    confidence: number | null
  }[]
}

export type BenchResponse = {
  specimen: string
  expected_verdict: Verdict | null
  sharpness: number | null
  lanes: LaneResult[]
}

export type SpecimenSummary = {
  filename: string
  brand: string
  expected_verdict: Verdict
  quality: string
  intended_defect: string
  title: string
  hint: string
}

export type StagedRow = {
  row: number
  applicant: string
  brand: string
  filename: string
  bucket: 'matched' | 'matched_fuzzy' | 'missing_image' | 'ambiguous'
  image: string | null
  candidate_filenames: string[]
  errors: string[]
}

export type StagedBatch = {
  batch_id: string
  rows: StagedRow[]
  summary: {
    matched: number
    matched_fuzzy: number
    missing_image: number
    ambiguous: number
    unused_images: string[]
  }
  blocks_commit: boolean
}

export type Job = {
  id: string
  scope: string
  state: 'running' | 'done' | 'error'
  total: number
  completed: number
  committed: number
  failed: number
  verdicts: Record<string, number>
  error: string | null
}
