import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RecordRow, RecordsPage } from '../api/client'
import { matchesQuery } from '../lib/search'

/**
 * Move through the queue the reviewer came from, without going back to the
 * inbox between every label.
 *
 * The filter and search arrive as URL search params, which keeps a link to a
 * record intact across a reload, and this applies the same predicate the inbox
 * does (lib/search) — if the two diverged, Next would walk a different set from
 * the one the reviewer was looking at.
 */

const FILTER_LABEL: Record<string, string> = {
  attention: 'Needs attention',
  pending: 'Awaiting AI verification',
  review: 'Review',
  fail: 'Fail',
  closed: 'Closed',
  '': 'All records',
}

export function QueueNav({
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
  if (index < 0) return null

  const params = new URLSearchParams()
  params.set('filter', filter)
  if (query) params.set('q', query)
  const search = params.toString() ? `?${params}` : ''

  const previous = index > 0 ? rows[index - 1] : null
  const next = index < rows.length - 1 ? rows[index + 1] : null

  return (
    <nav className="card queue-nav" aria-label="Queue navigation">
      <Step to={previous && `/records/${previous.id}${search}`} record={previous} direction="back" />

      <div className="queue-nav-place">
        <div className="queue-nav-count">
          {index + 1} of {rows.length}
        </div>
        <div className="queue-nav-filter">{FILTER_LABEL[filter] ?? 'Queue'}</div>
      </div>

      <Step to={next && `/records/${next.id}${search}`} record={next} direction="forward" />
    </nav>
  )
}

/** One end of the pair. Naming the record is what makes it worth pressing. */
function Step({
  to,
  record,
  direction,
}: {
  to: string | null
  record: RecordRow | null
  direction: 'back' | 'forward'
}) {
  const label = direction === 'back' ? '← Previous' : 'Next →'
  const align = direction === 'back' ? 'left' : 'right'

  if (!to || !record) {
    return (
      <div className={`queue-nav-step is-end ${align}`} aria-hidden="true">
        <span className="queue-nav-label">{label}</span>
        <span className="queue-nav-brand">
          {direction === 'back' ? 'Start of queue' : 'End of queue'}
        </span>
      </div>
    )
  }

  return (
    <Link className={`queue-nav-step ${align}`} to={to}>
      <span className="queue-nav-label">{label}</span>
      <span className="queue-nav-brand">{record.app_brand}</span>
    </Link>
  )
}
