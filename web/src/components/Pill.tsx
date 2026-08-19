import type { Verdict } from '../api/client'
import { PILL_TEXT, kindOf } from '../lib/verdict'

export function Pill({
  verdict,
  small = false,
  label,
}: {
  verdict: Verdict | null | undefined
  small?: boolean
  label?: string
}) {
  const kind = kindOf(verdict)
  return (
    <span className={`pill pill-${kind}${small ? ' pill-sm' : ''}`}>
      {label ?? PILL_TEXT[kind]}
    </span>
  )
}
