import { useEffect } from 'react'

/**
 * Escape closes a dialog, matching the backdrop click. On the document, not the
 * element: focus is usually in an input, and one route may own several dialogs,
 * so it is called once with a handler that closes them all.
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
