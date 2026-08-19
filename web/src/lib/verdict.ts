import type { Verdict } from '../api/client'

/** Prototype pill vocabulary — verdict is never colour alone (PRD §8). */
export const PILL_TEXT: Record<string, string> = {
  match: 'Match',
  review: 'Needs review',
  fail: 'Fail',
  pending: 'Awaiting AI',
}

export const DOT_COLOR: Record<string, string> = {
  match: 'var(--match-dot)',
  review: 'var(--review-dot)',
  fail: 'var(--fail-dot)',
  pending: 'var(--pending-dot)',
}

/** No verdict yet reads as *awaiting AI*, not as a fourth verdict (PRD §3.2). */
export function kindOf(verdict: Verdict | null | undefined) {
  return verdict ?? 'pending'
}
