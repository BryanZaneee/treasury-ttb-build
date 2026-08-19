import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { REVIEWER } from '../lib/session'
import { useToast } from '../lib/toast'

/**
 * Session actions, behind the reviewer's own name in the masthead.
 *
 * One action, and it is destructive, so it asks twice: the first press arms
 * it, the second runs it. There is no cancel beside the armed button — Close
 * is the way out, and a second control that also means "not that" is noise.
 */
export function SessionDialog({ onClose }: { onClose: () => void }) {
  const client = useQueryClient()
  const toast = useToast()
  const [armed, setArmed] = useState(false)

  // Escape closes, as it does for any modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const reset = useMutation({
    mutationFn: () =>
      api<{ reset_count: number }>('/fixtures', {
        method: 'POST',
        body: { mode: 'reset' },
        admin: true,
      }),
    onSuccess: (data) => {
      client.invalidateQueries()
      onClose()
      toast({
        kind: 'info',
        title: 'Store reset to the default state',
        body: `${data.reset_count} bundled sample labels restored, awaiting verification. The store as it was has been snapshotted.`,
      })
    },
    onError: (e) => toast({ kind: 'error', title: 'Reset failed', body: String(e) }),
  })

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        className="dialog dialog-sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="session-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-head">
          <h2 id="session-title">{REVIEWER.name}</h2>
          <p className="card-note">{REVIEWER.role}</p>
        </div>

        <div className="dialog-body">
          <div className="session-action-title">Reset to the default state</div>
          <p className="card-note">
            Deletes every filed record and every determination, and restores the 25 bundled
            sample labels awaiting verification. The store as it stands is snapshotted first,
            but nothing in the running app will bring it back. Requires the admin token.
          </p>
          {armed && (
            <div className="banner" style={{ marginTop: 14 }}>
              <div className="banner-mark" aria-hidden="true">
                !
              </div>
              <div className="banner-text">
                <strong>This cannot be undone from here.</strong> Press Reset everything again to
                wipe the store, or Close to leave it alone.
              </div>
            </div>
          )}
        </div>

        <div className="dialog-foot">
          <button
            className="btn btn-danger"
            disabled={reset.isPending}
            onClick={() => (armed ? reset.mutate() : setArmed(true))}
          >
            {reset.isPending && <span className="spinner spinner-dark" />}
            Reset everything
          </button>
          <button className="btn btn-quiet push" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
