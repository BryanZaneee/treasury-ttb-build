import { useRef } from 'react'

import { useFocusTrap } from '../lib/dialog'

/** A specimen at full size. The evidence behind a determination is too small to
 *  read in a 3:4 card, so every thumbnail in the app opens one of these. */
export function Lightbox({
  src,
  alt,
  caption,
  onClose,
}: {
  src: string
  alt: string
  caption: string
  onClose: () => void
}) {
  // React does not polyfill `autoFocus` on a div, so it never took focus and
  // Tab walked straight into the page this dialog claims to have hidden.
  const panel = useRef<HTMLDivElement>(null)
  useFocusTrap(panel)
  return (
    <div
      ref={panel}
      className="dialog-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={alt}
      tabIndex={-1}
      onClick={onClose}
    >
      <figure className="lightbox">
        <img src={src} alt={alt} />
        <figcaption className="mono">{caption}</figcaption>
      </figure>
    </div>
  )
}
