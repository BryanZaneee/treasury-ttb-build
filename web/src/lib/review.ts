/** S10: the minimised panel survives a reload, on this device. The record id
 *  rides along so a stale flag cannot collapse a different record. */
const KEY = 'ttb.review'

export type ReviewPanel = { recordId: string; minimised: boolean }

export function readPanel(recordId: string): boolean {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return false
    const saved = JSON.parse(raw) as ReviewPanel
    return saved.recordId === recordId && saved.minimised
  } catch {
    return false
  }
}

export function writePanel(panel: ReviewPanel): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(panel))
  } catch {
    /* a full or blocked store loses the preference, not the review */
  }
}
