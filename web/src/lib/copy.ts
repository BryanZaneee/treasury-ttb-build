import type { RecordRow, Verdict } from '../api/client'

/** Field labels as the prototype writes them (PRD §3.1, §6.1). */
export const FIELD_LABEL: Record<string, string> = {
  brand: 'Brand name',
  classType: 'Class / type',
  abv: 'Alcohol content',
  net: 'Net contents',
  producer: 'Bottler / producer',
  origin: 'Country of origin',
  warning: 'Government warning',
}

/* Past tense and plural-agnostic: "7 needs review" is not a sentence. */
const VERDICT_WORD: Record<string, string> = {
  match: 'matched',
  review: 'to review',
  fail: 'failed',
  invalid: 'not a label',
}

/**
 * A run's verdict mix as a sentence — "2 failed and 1 to review". Intl.ListFormat
 * rather than a join, so it reads as prose and not as the verdict enum.
 */
const LIST = new Intl.ListFormat('en', { style: 'long', type: 'conjunction' })

export function verdictSummary(verdicts: Record<string, number>): string {
  return LIST.format(
    Object.keys(VERDICT_WORD)
      .filter((v) => verdicts[v])
      .map((v) => `${verdicts[v]} ${VERDICT_WORD[v]}`),
  )
}

/**
 * The per-row image button, per pairing bucket (PRD §5.5). Keyed on the bucket,
 * not on whether the row has an image: an ambiguous row has none *because* more
 * than one matched, so "Attach" would name the opposite of the problem.
 */
export const PICK_LABEL: Record<string, string> = {
  matched: 'Change',
  matched_fuzzy: 'Change',
  missing_image: 'Attach',
  ambiguous: 'Select',
}

/** Capture-quality vocabulary (PRD §5.2) in reviewer-facing words. */
export const QUALITY_LABEL: Record<string, string> = {
  normal: 'Clean capture',
  blurry: 'Out of focus',
  heavyBlur: 'Heavily blurred',
  glare: 'Specular glare',
  pixelated: 'Low resolution',
  angled: 'Off-axis capture',
  dark: 'Underexposed',
  damaged: 'Damaged label',
  cropped: 'Cropped frame',
  '': 'Clean capture',
}

export const RESULT_COPY: Record<string, string> = {
  match: 'Every required field agrees with the application of record.',
  review: 'Same content, different presentation. An agent should confirm before closing.',
  fail: 'One or more fields differ in content, are missing, or could not be read.',
  invalid:
    'The image filed is not an alcohol beverage label. Nothing was adjudicated. Ask the applicant for the label image.',
  pending: 'Not yet verified.',
}

export function received(record: RecordRow) {
  return record.received.slice(0, 10)
}

/**
 * What a field's recorded values should read as. A record restored from an older
 * export has a verdict and no evidence, and "Not on label" would state something
 * the store does not know — beside a Match verdict, a contradiction.
 */
export function fieldValues(field: { app_value: string | null; label_value: string | null }) {
  const recorded = field.app_value != null || field.label_value != null
  return {
    app: field.app_value || (recorded ? 'Not stated' : 'Not recorded'),
    label: field.label_value || (recorded ? 'Not on label' : 'Not recorded'),
    recorded,
  }
}

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

/** Detectable because the backend stores the reader that ran, not the configured one. */
export function readByFallback(record: Pick<RecordRow, 'reader_provider'>, configured?: string) {
  if (!configured || configured === 'ocr') return false
  return record.reader_provider === 'ocr'
}

export const FALLBACK_TITLE = 'Read by local OCR: accuracy may be lower'

export const FALLBACK_BODY =
  'The vision reader was unavailable, so the label was read by local OCR. ' +
  'Blurred, angled or low-contrast captures read less reliably this way. ' +
  'Confirm the fields against the label before closing the record.'
