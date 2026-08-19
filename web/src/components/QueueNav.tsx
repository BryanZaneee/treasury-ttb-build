import type { ReactNode } from 'react'
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
 *
 * `children` sits above the queue position in the centre column, which is how
 * the determination view puts its verdict between the two steps. The component
 * always renders: it used to return null while its own query was in flight and
 * whenever the record was outside the current queue, so the bar vanished and
 * reappeared on every step — and now that it carries the verdict, that would
 * take the verdict with it.
 */

const FILTER_LABEL: Record<string, string> = {
  attention: 'Needs attention',
  pending: 'Awaiting AI verification',
  review: 'Review',
  fail: 'Fail',
  closed: 'Closed',
  '': 'All records',
}

function useQueuePlace(currentId: string, filter: string, query: string) {
  const records = useQuery({
    queryKey: ['records', filter],
    queryFn: () => api<RecordsPage>(`/records${filter ? `?filter=${filter}` : ''}`),
  })

  const rows = (records.data?.records ?? []).filter((r) => matchesQuery(r, query))
  const index = rows.findIndex((r) => r.id === currentId)

  const params = new URLSearchParams()
  params.set('filter', filter)
  if (query) params.set('q', query)
  const search = params.toString() ? `?${params}` : ''

  return {
    index,
    total: rows.length,
    label: FILTER_LABEL[filter] ?? 'Queue',
    previous: index > 0 ? rows[index - 1] : null,
    next: index >= 0 && index < rows.length - 1 ? rows[index + 1] : null,
    search,
  }
}

export function QueueNav({
  currentId,
  filter,
  query,
  className = 'card queue-nav',
  children,
}: {
  currentId: string
  filter: string
  query: string
  className?: string
  children?: ReactNode
}) {
  const place = useQueuePlace(currentId, filter, query)

  return (
    <nav className={className} aria-label="Queue navigation">
      <Step
        to={place.previous && `/records/${place.previous.id}${place.search}`}
        record={place.previous}
        direction="back"
      />

      <div className="queue-nav-place">
        {children}
        <div className="queue-nav-count">
          {place.index < 0 ? 'Not in this queue' : `${place.index + 1} of ${place.total}`}
        </div>
        <div className="queue-nav-filter">{place.label}</div>
      </div>

      <Step
        to={place.next && `/records/${place.next.id}${place.search}`}
        record={place.next}
        direction="forward"
      />
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
