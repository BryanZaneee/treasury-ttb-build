import { useEffect } from 'react'

/**
 * Escape closes a dialog, matching the backdrop click every dialog already has.
 *
 * Listens on the document rather than the dialog element, because focus is
 * often inside an input in the dialog body, and because a route may have more
 * than one dialog: the route calls this once with a handler that closes them
 * all, which keeps the hook out of a conditional branch.
 */
export function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
}
