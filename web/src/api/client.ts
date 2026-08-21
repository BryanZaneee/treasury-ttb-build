/**
 * API client: the one place that knows the base URL and the shared token.
 *
 * PRD §8 has no user accounts, so mutating endpoints take a shared bearer token
 * (VITE_ACCESS_TOKEN in dev). The reader API key never reaches the browser.
 *
 * Every URL goes through `apiUrl`, not a bare `/api`: `import.meta.env.BASE_URL`
 * mirrors Vite `base`, and a bare path would escape the production subpath.
 */
const ROOT = import.meta.env.BASE_URL.replace(/\/$/, '')
const BASE = `${ROOT}/api`

export const apiUrl = (path: string) => `${BASE}${path}`

/**
 * The Cloudflare zone caches everything and ignores `Cache-Control: no-store`,
 * so a unique query param makes every read a distinct URL.
 * ponytail: client-side workaround; the fix is a cache-bypass rule on the zone.
 */
const uncacheable = (url: string) =>
  `${url}${url.includes('?') ? '&' : '?'}_=${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`

export const freshUrl = (path: string) => uncacheable(apiUrl(path))

export const imageUrl = (name: string) => `${BASE}/images/${encodeURIComponent(name)}`
const ACCESS_TOKEN = import.meta.env.VITE_ACCESS_TOKEN ?? ''

/**
 * The admin token gates replacing the store and resetting fixtures (PRD §8), so
 * it must not be compiled into a bundle anyone can fetch - `deploy.sh` builds on
 * the app host, against that host's .env. A build-time value stays for local dev
 * and CI; production leaves VITE_ADMIN_TOKEN empty and a reviewer supplies one,
 * held for this tab only.
 */
const ADMIN_KEY = 'ttb.admin-token'

function storedAdminToken(): string {
  try {
    return sessionStorage.getItem(ADMIN_KEY) ?? ''
  } catch {
    return '' // private mode, or storage disabled
  }
}

let adminToken = (import.meta.env.VITE_ADMIN_TOKEN ?? '') || storedAdminToken()

export const hasAdminToken = () => Boolean(adminToken)

export function setAdminToken(token: string) {
  adminToken = token.trim()
  try {
    sessionStorage.setItem(ADMIN_KEY, adminToken)
  } catch {
    // Not persisting is survivable; the token still works for this page.
  }
}

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
  /** CSV exports come back as a file, not JSON. */
  blob?: boolean
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { method = 'GET', body, admin = false, form, blob = false } = options
  const headers: Record<string, string> = {}
  const token = admin ? adminToken : ACCESS_TOKEN
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
  if (blob) return (await response.blob()) as T
  return (await response.json()) as T
}

/** `invalid` extends PRD §3.2's enum: not a label, rather than a failed one. */
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

/** One record's outcome; both kinds name the record, so the inbox can release it. */
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

/**
 * Download a file the API gates on a token. A plain `<a download>` cannot carry
 * an Authorization header, so the body is fetched and saved from a blob.
 */
export async function download(path: string, filename: string, admin = false) {
  const blob = await api<Blob>(path, { admin, blob: true })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
