/** Inbox search across ID, applicant, brand and filename (S5). Shared so the
 *  determination view's worklist reproduces the inbox's filtered set exactly. */
const loosely = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '')

export type Searchable = {
  id: string
  applicant: string
  app_brand: string
  filename: string
}

export function matchesQuery(record: Searchable, query: string): boolean {
  // Guarded on the needle rather than the raw query: a punctuation-only search
  // has nothing to match on and is treated as no search, which is what the old
  // `query.trim()` guard also did, by way of ''.includes('') - but by accident.
  const needle = loosely(query)
  if (!needle) return true
  return [record.id, record.applicant, record.app_brand, record.filename].some((v) =>
    loosely(v ?? '').includes(needle),
  )
}
