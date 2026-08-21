import { describe, expect, test } from 'vitest'
import { matchesQuery } from './search'
import {
  PICK_LABEL,
  PILL_TEXT,
  contestedAccept,
  fieldValues,
  kindOf,
  readByFallback,
  verdictSummary,
} from './copy'

const record = (over: Partial<Parameters<typeof matchesQuery>[0]> = {}) => ({
  id: 'COLA-2026-4100',
  applicant: "Stone's Throw Spirits Co.",
  app_brand: 'Old Tom Distillery',
  filename: 'old-tom-pass.jpg',
  ...over,
})

describe('matchesQuery (S5)', () => {
  test('an empty query matches everything', () => {
    expect(matchesQuery(record(), '')).toBe(true)
    expect(matchesQuery(record(), '   ')).toBe(true)
  })

  test('a punctuation-only query is treated as no search', () => {
    // Pinned because it used to fall out of ''.includes('') rather than being
    // decided: the guard now says so, and this is what says it stays that way.
    for (const query of ['---', '...', '///', '-.-']) {
      expect(matchesQuery(record(), query)).toBe(true)
      expect(matchesQuery(record({ id: 'ZZZ', applicant: 'ZZZ', app_brand: 'ZZZ', filename: 'ZZZ' }), query)).toBe(true)
    }
  })

  test('searches all four fields the story names', () => {
    expect(matchesQuery(record(), '4100')).toBe(true)
    expect(matchesQuery(record(), 'Spirits')).toBe(true)
    expect(matchesQuery(record(), 'Old Tom')).toBe(true)
    expect(matchesQuery(record(), 'pass.jpg')).toBe(true)
    expect(matchesQuery(record(), 'harbor mist')).toBe(false)
  })

  test('is case-insensitive', () => {
    expect(matchesQuery(record(), 'OLD TOM')).toBe(true)
    expect(matchesQuery(record(), 'old tom')).toBe(true)
  })

  test('is punctuation-insensitive in both directions', () => {
    // The apostrophe and the hyphens are in the data, not the query...
    expect(matchesQuery(record(), 'stones throw')).toBe(true)
    expect(matchesQuery(record(), 'oldtompass')).toBe(true)
    // ...and punctuation in the query must not defeat a match either.
    expect(matchesQuery(record(), 'COLA-2026-4100')).toBe(true)
    expect(matchesQuery(record(), "Stone's Throw")).toBe(true)
  })

  test('tolerates a null field without throwing', () => {
    expect(matchesQuery(record({ applicant: null as unknown as string }), 'old tom')).toBe(true)
  })
})

describe('verdict helpers (PRD §3.2)', () => {
  test('no verdict yet reads as pending, not as a fourth verdict', () => {
    expect(kindOf(null)).toBe('pending')
    expect(kindOf(undefined)).toBe('pending')
    expect(kindOf('match')).toBe('match')
  })

  test('every verdict has pill text, so colour is never the only signal (§8)', () => {
    for (const kind of ['match', 'review', 'fail', 'invalid', 'pending']) {
      expect(PILL_TEXT[kind]).toBeTruthy()
    }
  })

  test('only a failed check or a non-label is worth challenging', () => {
    expect(contestedAccept('fail')).toBe(true)
    expect(contestedAccept('invalid')).toBe(true)
    // A review verdict is the ordinary thing a reviewer waves through.
    expect(contestedAccept('review')).toBe(false)
    expect(contestedAccept('match')).toBe(false)
    expect(contestedAccept(null)).toBe(false)
  })
})

describe('fieldValues', () => {
  test('distinguishes never-recorded from recorded-but-absent', () => {
    expect(fieldValues({ app_value: null, label_value: null })).toMatchObject({
      app: 'Not recorded',
      label: 'Not recorded',
      recorded: false,
    })
    // One side present means the field was adjudicated, so the empty side is a
    // finding ("Not on label"), not a gap in the record.
    expect(fieldValues({ app_value: '750 mL', label_value: null })).toMatchObject({
      app: '750 mL',
      label: 'Not on label',
      recorded: true,
    })
    expect(fieldValues({ app_value: null, label_value: '75 cl' })).toMatchObject({
      app: 'Not stated',
      label: '75 cl',
    })
  })
})

describe('readByFallback', () => {
  test('flags a record read by OCR while a vision reader was configured', () => {
    expect(readByFallback({ reader_provider: 'ocr' }, 'openai')).toBe(true)
    expect(readByFallback({ reader_provider: 'openai' }, 'openai')).toBe(false)
  })

  test('is not a fallback when OCR is what was configured', () => {
    expect(readByFallback({ reader_provider: 'ocr' }, 'ocr')).toBe(false)
    expect(readByFallback({ reader_provider: 'ocr' }, undefined)).toBe(false)
  })
})

describe('PICK_LABEL (PRD §5.5 buckets)', () => {
  test('an ambiguous row asks the reviewer to select, not to attach', () => {
    // It has no image because *too many* matched. "Attach" would name the
    // opposite problem.
    expect(PICK_LABEL.ambiguous).toBe('Select')
    expect(PICK_LABEL.missing_image).toBe('Attach')
    expect(PICK_LABEL.matched).toBe('Change')
    expect(PICK_LABEL.matched_fuzzy).toBe('Change')
  })
})

describe('verdictSummary', () => {
  test('reads as a sentence, not as the verdict enum on bullets', () => {
    expect(verdictSummary({ fail: 2, review: 1 })).toBe('1 to review and 2 failed')
    expect(verdictSummary({ match: 2, review: 2, fail: 1 })).toBe(
      '2 matched, 2 to review, and 1 failed',
    )
  })

  test('one verdict needs no conjunction, and none needs no sentence', () => {
    expect(verdictSummary({ match: 3 })).toBe('3 matched')
    expect(verdictSummary({})).toBe('')
  })

  test('orders the way a reviewer works a queue, not by insertion', () => {
    expect(verdictSummary({ fail: 1, match: 1 })).toBe('1 matched and 1 failed')
  })
})
