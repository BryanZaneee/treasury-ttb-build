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

export const apiUrl = (path: string) => `${BASE}${path}`

/**
 * The Cloudflare zone in front of the deployment caches everything and ignores
 * origin `Cache-Control: no-store`, so it served stale inbox counts. A unique
 * query param makes every read a distinct URL.
 * ponytail: client-side workaround; the real fix is a cache-bypass rule for
 * /ttb-build/api/* in the Cloudflare dashboard.
 */
const uncacheable = (url: string) =>
  `${url}${url.includes('?') ? '&' : '?'}_=${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

export const freshUrl = (path: string) => uncacheable(apiUrl(path))

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

  // Reads must never be answered from a cache; writes are never cached.
  const url = method === 'GET' ? uncacheable(`${BASE}${path}`) : `${BASE}${path}`
  const response = await fetch(url, {
    method,
    headers,
    cache: 'no-store',
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

/**
 * `invalid` extends PRD §3.2's three-value enum: the vision reader flags a
 * specimen that is not a label at all, which is not a label that failed.
 */
export type Verdict = 'match' | 'review' | 'fail' | 'invalid'

export type Health = {
  store_readable: boolean | null
  images_writable: boolean | null
  reader_reachable: boolean | null
  prompt_version: string | null
  provider: string
  model: string
  calls_today: number
  counters: Record<string, number>
}

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
  prompt_version: string | null
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
  /** Whole-store count, so a caller wanting a number need not fetch the rows. */
  total: number
}

export type RecordsPage = { records: RecordRow[]; counts: Counts }

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

/** One record's outcome, appended as the job runs. `record` and `error` both
 *  name the record, which is how the inbox knows a row has finished. */
export type JobEvent = {
  event: 'record' | 'error' | 'done'
  record_id?: string
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
  record_ids: string[]
  events: JobEvent[]
  error: string | null
}

/** POST /store/import — restoring the record store from an exported mirror. */
export type StoreImport = {
  imported: number
  skipped: number
  errors: string[]
}
