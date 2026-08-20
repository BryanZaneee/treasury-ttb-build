import type { RecordRow } from '../api/client'

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
 * What a field's recorded values should read as.
 *
 * The CSV mirror carries verdict and note but not the observed values (PRD
 * §4.2), so a record restored from an export has a verdict and no evidence.
 * Rendering that as "Not on label" states something the store does not know —
 * and next to a Match verdict it reads as a contradiction.
 */
export function fieldValues(field: { app_value: string | null; label_value: string | null }) {
  const recorded = field.app_value != null || field.label_value != null
  return {
    app: field.app_value || (recorded ? 'Not stated' : 'Not recorded'),
    label: field.label_value || (recorded ? 'Not on label' : 'Not recorded'),
    recorded,
  }
}
