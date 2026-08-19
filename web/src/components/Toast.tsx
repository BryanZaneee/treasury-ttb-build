import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ToastContext } from '../lib/toast'
import type { Toast } from '../lib/toast'

/**
 * Toasts exist for one thing: telling a reviewer that a determination was not
 * produced the way they would expect — chiefly that the vision reader was
 * unavailable and the label was read by local OCR instead, which is markedly
 * less accurate on blurred, angled or low-contrast captures.
 *
 * Announced in a live region, because a reviewer working the queue by keyboard
 * has no reason to be looking at the bottom-right of the screen (PRD §8).
 */

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.random()
    setToasts((prev) => [...prev, { ...t, id }])
    // Long enough to read two lines without hunting for a dismiss control.
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 9000)
  }, [])

  const value = useMemo(() => push, [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <div className="toast-title">{t.title}</div>
            {t.body && <div className="toast-body">{t.body}</div>}
            <button
              className="toast-close"
              aria-label="Dismiss notification"
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
