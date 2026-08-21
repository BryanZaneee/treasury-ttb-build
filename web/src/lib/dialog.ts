import { useEffect } from 'react'
import type { RefObject } from 'react'

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

const FOCUSABLE =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * Focus management for an `aria-modal` dialog: focus moves in on open, Tab is
 * kept inside, and the opener gets focus back on close. `aria-modal` tells
 * assistive tech to ignore the page behind, so a dialog Tab can walk out of is
 * lying about itself - and axe cannot see focus behaviour, only markup.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const panel = ref.current
    if (!panel) return
    const opener = document.activeElement as HTMLElement | null

    const focusable = () =>
      Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true',
      )

    const items = focusable()
    ;(items[0] ?? panel).focus()

    // On the document, not the panel: a listener on the panel stops firing the
    // moment focus has already escaped, which is the case worth catching.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const current = focusable()
      if (current.length === 0) {
        e.preventDefault()
        panel.focus()
        return
      }
      const first = current[0]
      const last = current[current.length - 1]
      const active = document.activeElement
      if (!panel.contains(active)) {
        e.preventDefault()
        first.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      } else if (e.shiftKey && active === first) {
        e.preventDefault()
        last.focus()
      }
    }

    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus?.()
    }
  }, [ref])
}
