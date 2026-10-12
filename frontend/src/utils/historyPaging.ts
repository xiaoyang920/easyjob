export interface QuestionPreview { messageId: string; question: string; answer?: string; hasImage?: boolean }
export interface HistoryWindow { beforeCursor: string | null; afterCursor: string | null; hasOlder: boolean; hasNewer: boolean }
export function emptyHistoryWindow(): HistoryWindow {
  return { beforeCursor: null, afterCursor: null, hasOlder: false, hasNewer: false }
}
export function historyPage(data: any) {
  if (Array.isArray(data)) return { ...emptyHistoryWindow(), items: data }
  if (!data || !Array.isArray(data.items)) throw new Error('历史消息格式无效')
  return { items: data.items, beforeCursor: data.beforeCursor || null, afterCursor: data.afterCursor || null,
    hasOlder: !!data.hasOlder, hasNewer: !!data.hasNewer }
}
export function mergeHistory<T extends { itemId?: string }>(current: T[], incoming: T[], prepend = false): T[] {
  const existing = new Map(current.filter(m => m.itemId).map(m => [m.itemId, m]))
  const items = incoming.map(m => existing.get(m.itemId) || m)
  const seen = new Set<string>()
  return (prepend ? [...items, ...current] : [...current, ...items]).filter(m => {
    if (!m.itemId) return true
    if (seen.has(m.itemId)) return false
    seen.add(m.itemId); return true
  })
}
export function questionPreviews(index: QuestionPreview[], messages: any[]): QuestionPreview[] {
  const byId = new Map(index.map(q => [q.messageId, { ...q }]))
  messages.forEach((m, i) => {
    if (m.role !== 'user') return
    const id = m.messageId || m.itemId
    if (!id) return
    let answer = ''
    for (let n = i + 1; n < messages.length && messages[n].role !== 'user'; n++) {
      if (messages[n].content) { answer = messages[n].content.slice(0, 384); break }
    }
    const old = byId.get(id)
    byId.set(id, { messageId: id, question: m.content.slice(0, 256), hasImage: !!m.image,
      answer: answer || old?.answer || '' })
  })
  // Snowflake IDs stay strings throughout; converting to Number loses precision.
  return [...byId.values()].sort((a, b) => {
    const x = a.messageId, y = b.messageId
    if (/^\d+$/.test(x) && /^\d+$/.test(y)) return x.length - y.length || x.localeCompare(y)
    if (/^\d+$/.test(x)) return -1
    if (/^\d+$/.test(y)) return 1
    return 0
  })
}
