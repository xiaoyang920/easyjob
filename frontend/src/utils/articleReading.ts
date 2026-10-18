export type ReadingBookmark = { articleId: string; fingerprint: string; headingId: string; headingText: string; fraction: number; updatedAt: number }
const PREFIX = 'easyjob:reading-position:v1:'

// Layout identifiers only, never security or content-integrity proofs.
export function readingFingerprint(text: string): string {
  let hash = 2166136261
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619)
  return (hash >>> 0).toString(36)
}
export function sectionId(text: string, occurrence: number): string { return `section-${readingFingerprint(text.trim())}-${occurrence}` }
function key() { return PREFIX + (localStorage.getItem('userId') || 'guest') }
function entries(): ReadingBookmark[] {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(key()) || '[]')
    return Array.isArray(data) ? data.filter((r): r is ReadingBookmark => !!r && typeof r.articleId === 'string' && typeof r.fingerprint === 'string' && typeof r.headingId === 'string' && typeof r.headingText === 'string' && Number.isFinite(r.fraction) && r.fraction >= 0 && r.fraction <= 1 && Number.isFinite(r.updatedAt)).slice(0, 50) : []
  } catch { return [] }
}
export function readBookmark(articleId: string, fingerprint: string): ReadingBookmark | undefined { return entries().find(r => r.articleId === articleId && r.fingerprint === fingerprint) }
export function saveBookmark(bookmark: ReadingBookmark) {
  try { localStorage.setItem(key(), JSON.stringify([bookmark, ...entries().filter(r => r.articleId !== bookmark.articleId)].slice(0, 50))) } catch { /* Storage is optional. */ }
}
