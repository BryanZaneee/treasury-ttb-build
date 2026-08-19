/**
 * Inbox search: case- and punctuation-insensitive across ID, applicant, brand
 * and filename (S5).
 *
 * Shared because the determination view's worklist has to reproduce the inbox's
 * filtered set exactly. If the two predicates ever diverged, the list a reviewer
 * clicks through would quietly stop matching the queue they came from.
 */
const loosely = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '')

export type Searchable = {
  id: string
  applicant: string
  app_brand: string
  filename: string
}

export function matchesQuery(record: Searchable, query: string): boolean {
  if (!query.trim()) return true
  const needle = loosely(query)
  return [record.id, record.applicant, record.app_brand, record.filename].some((v) =>
    loosely(v ?? '').includes(needle),
  )
}
