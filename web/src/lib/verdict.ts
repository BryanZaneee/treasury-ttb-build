import type { Verdict } from '../api/client'

/** Prototype pill vocabulary — verdict is never colour alone (PRD §8). */
export const PILL_TEXT: Record<string, string> = {
  match: 'Match',
  review: 'Needs review',
  fail: 'Fail',
  invalid: 'Not a label',
  pending: 'Awaiting AI verification',
}

export const DOT_COLOR: Record<string, string> = {
  match: 'var(--match-dot)',
  review: 'var(--review-dot)',
  fail: 'var(--fail-dot)',
  invalid: 'var(--invalid-dot)',
  pending: 'var(--pending-dot)',
}

/** No verdict yet reads as *awaiting AI*, not as a fourth verdict (PRD §3.2). */
export function kindOf(verdict: Verdict | null | undefined) {
  return verdict ?? 'pending'
}

/**
 * Whether accepting this verdict should be challenged before it is recorded.
 *
 * PRD §5.1 records an override for anything that is not a `match`, and that is
 * unchanged. What is contested is narrower: a `review` verdict is a difference
 * in presentation over content that agrees, which is the ordinary thing a
 * reviewer is here to wave through, so only a failed check or a specimen that
 * is not a label is worth interrupting them for.
 */
export function contestedAccept(verdict: Verdict | null | undefined) {
  return verdict === 'fail' || verdict === 'invalid'
}
