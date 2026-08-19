import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RecordsPage } from '../api/client'
import { matchesQuery } from '../lib/search'
import { DOT_COLOR, kindOf } from '../lib/verdict'
import { Pill } from './Pill'

/**
 * The queue the reviewer came from, carried into the determination view so they
 * can work through it without going back to the inbox between every label.
 *
 * The filter and search arrive as URL search params, which keeps the list
 * deep-linkable and intact across a reload, and it applies the same predicate
 * the inbox does (lib/search) — if the two ever diverged the list would quietly
 * stop matching the queue it claims to be.
 */

const FILTER_LABEL: Record<string, string> = {
  attention: 'Needs attention',
  pending: 'Awaiting AI',
  review: 'Review',
  fail: 'Fail',
  closed: 'Closed',
  '': 'All records',
}

export function Worklist({
  currentId,
  filter,
  query,
}: {
  currentId: string
  filter: string
  query: string
}) {
  const records = useQuery({
    queryKey: ['records', filter],
    queryFn: () => api<RecordsPage>(`/records${filter ? `?filter=${filter}` : ''}`),
  })

  const rows = (records.data?.records ?? []).filter((r) => matchesQuery(r, query))
  const index = rows.findIndex((r) => r.id === currentId)
  const params = new URLSearchParams()
  if (filter) params.set('filter', filter)
  if (query) params.set('q', query)
  const search = params.toString() ? `?${params}` : ''

  const previous = index > 0 ? rows[index - 1] : null
  const next = index >= 0 && index < rows.length - 1 ? rows[index + 1] : null

  return (
    <div className="card worklist">
      <div className="card-pad" style={{ paddingBottom: 12 }}>
        <div className="card-title">{FILTER_LABEL[filter] ?? 'Worklist'}</div>
        <p className="card-note">
          {index >= 0 ? `${index + 1} of ${rows.length}` : `${rows.length} records`}
          {query ? ` · matching “${query}”` : ''}
        </p>
        <div className="row" style={{ gap: 8, marginTop: 10 }}>
          <Link
            className={`btn btn-quiet btn-sm${previous ? '' : ' disabled'}`}
            to={previous ? `/records/${previous.id}${search}` : '#'}
            aria-disabled={!previous}
            tabIndex={previous ? undefined : -1}
          >
            ← Previous
          </Link>
          <Link
            className={`btn btn-quiet btn-sm${next ? '' : ' disabled'}`}
            to={next ? `/records/${next.id}${search}` : '#'}
            aria-disabled={!next}
            tabIndex={next ? undefined : -1}
          >
            Next →
          </Link>
        </div>
      </div>

      <div className="worklist-scroll">
        {rows.map((r) => (
          <Link
            key={r.id}
            to={`/records/${r.id}${search}`}
            className="worklist-item"
            aria-current={r.id === currentId ? 'true' : undefined}
          >
            <span
              className="worklist-dot"
              style={{ background: r.decision ? '#c6d0da' : DOT_COLOR[kindOf(r.result)] }}
            />
            <span style={{ minWidth: 0 }}>
              <span className="worklist-brand">{r.app_brand}</span>
              <span className="worklist-meta">{r.id}</span>
              <span style={{ display: 'block', marginTop: 5 }}>
                <Pill verdict={r.result} small />
              </span>
            </span>
          </Link>
        ))}
        {rows.length === 0 && (
          <div className="empty" style={{ padding: '28px 16px' }}>
            <div className="empty-hint">Nothing else in this view.</div>
          </div>
        )}
      </div>
    </div>
  )
}
