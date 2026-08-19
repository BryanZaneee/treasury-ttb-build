import type { RecordRow } from '../api/client'

/**
 * A record was read by the OCR fallback when the reader that actually produced
 * it is `ocr` but that is not what the service is configured to use. The
 * backend records the reader that ran, not the one that was asked for, which is
 * what makes this detectable per record rather than per deployment.
 */
export function readByFallback(record: Pick<RecordRow, 'reader_provider'>, configured?: string) {
  if (!configured || configured === 'ocr') return false
  return record.reader_provider === 'ocr'
}

export const FALLBACK_TITLE = 'Read by local OCR — accuracy may be lower'

export const FALLBACK_BODY =
  'The vision reader was unavailable, so the label was read by local OCR. ' +
  'Blurred, angled or low-contrast captures read less reliably this way. ' +
  'Confirm the fields against the specimen before closing the record.'
