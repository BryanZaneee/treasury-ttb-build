import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ToastContext } from '../lib/toast'
import type { Toast } from '../lib/toast'

/**
 * The outcome of something the reviewer started and stopped watching. Announced
 * in a live region: working the queue by keyboard is no reason to miss it (§8).
 */

const TOAST_MS = 12_000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback(
    (id: number) => setToasts((prev) => prev.filter((x) => x.id !== id)),
    [],
  )

  const push = useCallback(
    (t: Omit<Toast, 'id'>) => {
      const id = Date.now() + Math.random()
      setToasts((prev) => [...prev, { ...t, id }])
      // All of them, actions included: filing one after another stacked notices,
      // and everything a toast offers is reachable again from the inbox.
      setTimeout(() => dismiss(id), TOAST_MS)
    },
    [dismiss],
  )

  const value = useMemo(() => push, [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <div className="toast-title">{t.title}</div>
            {t.body && <div className="toast-body">{t.body}</div>}
            {t.actions && t.actions.length > 0 && (
              <div className="toast-actions">
                {t.actions.map((a) => (
                  <button
                    key={a.label}
                    className={`btn btn-sm${a.tone === 'quiet' ? ' btn-quiet' : ''}`}
                    onClick={() => {
                      if (a.onClick() !== true) dismiss(t.id)
                    }}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            )}
            <button
              className="toast-close"
              aria-label="Dismiss notification"
              onClick={() => dismiss(t.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
