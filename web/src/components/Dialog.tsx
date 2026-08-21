import { useRef } from 'react'
import type { ReactNode } from 'react'

import { useFocusTrap } from '../lib/dialog'

/** The modal shell: backdrop, focus semantics and the head/body/foot frame.
 *  Only the chrome is shared - every caller writes its own copy. */
export function Dialog({
  title,
  titleId,
  subtitle,
  wide = false,
  onClose,
  children,
  footer,
}: {
  title: string
  titleId: string
  subtitle?: ReactNode
  /** The picker and the bulk decision need the room; confirmations do not. */
  wide?: boolean
  onClose: () => void
  children: ReactNode
  footer: ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  useFocusTrap(panel)
  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div
        ref={panel}
        className={`dialog${wide ? '' : ' dialog-sm'}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        // -1 so the panel itself can hold focus when it has no focusable child.
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          {subtitle}
        </div>
        <div className="dialog-body">{children}</div>
        <div className="dialog-foot">{footer}</div>
      </div>
    </div>
  )
}
