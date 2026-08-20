import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RecordRow, RecordsPage } from '../api/client'
import { matchesQuery } from '../lib/search'

/**
 * Step through the queue the reviewer came from. Filter and search arrive as
 * URL params and go through lib/search, the same predicate the inbox uses — if
 * they diverged, Next would walk a different set. Always renders, including
 * while loading: it carries the verdict in `children`.
 */

function useQueuePlace(currentId: string, filter: string, query: string) {
  // Deliberately not invalidated by a decision - see RecordDetail's refresh().
  // Deciding a record drops it out of the `attention` filter (`decision IS
  // NULL`), so refetching this list mid-review would delete the reviewer's own
  // position from under them and dead-end both Previous and Next. The inbox
  // refetches on mount, so it is still truthful when they go back to it.
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
        {/* Where this record sits in the queue being stepped through, so the
            reviewer knows how much of it is left before pressing Next. */}
        {place.total > 0 && (
          <div className="queue-nav-count">
            {place.index >= 0
              ? `${place.index + 1} of ${place.total} in this queue`
              : `${place.total} in this queue`}
          </div>
        )}
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
