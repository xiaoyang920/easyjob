export const SEARCH_HISTORY_PREFIX = 'easyjob:search-history:v1:'
export const SEARCH_HISTORY_LIMIT = 10
export const SEARCH_QUERY_LIMIT = 200
type HistoryStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function browserStorage(): HistoryStorage | undefined {
  try { return window.localStorage } catch { return undefined }
}

export function searchHistoryKey(storage: HistoryStorage | undefined = browserStorage()): string {
  try {
    const userId = storage?.getItem('token') ? storage.getItem('userId') : null
    return SEARCH_HISTORY_PREFIX + (userId ? `user:${userId}` : 'guest')
  } catch { return SEARCH_HISTORY_PREFIX + 'guest' }
}

function validEntries(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value.filter((entry): entry is string => {
    if (typeof entry !== 'string') return false
    const term = entry.trim()
    const identity = term.toLowerCase()
    if (!term || term.length > SEARCH_QUERY_LIMIT || seen.has(identity)) return false
    seen.add(identity)
    return true
  }).map(entry => entry.trim()).slice(0, SEARCH_HISTORY_LIMIT)
}

export function readSearchHistory(storage: HistoryStorage | undefined = browserStorage()): string[] {
  try { return validEntries(JSON.parse(storage?.getItem(searchHistoryKey(storage)) || '[]')) }
  catch { return [] }
}

export function rememberSearch(query: string, storage: HistoryStorage | undefined = browserStorage()): string[] {
  const term = query.trim()
  const previous = readSearchHistory(storage)
  if (!term || term.length > SEARCH_QUERY_LIMIT) return previous
  const entries = [term, ...previous.filter(entry => entry.toLowerCase() !== term.toLowerCase())].slice(0, SEARCH_HISTORY_LIMIT)
  try { storage?.setItem(searchHistoryKey(storage), JSON.stringify(entries)) } catch { /* 禁用存储时仍允许搜索。 */ }
  return entries
}

export function deleteSearch(query: string, storage: HistoryStorage | undefined = browserStorage()): string[] {
  const entries = readSearchHistory(storage).filter(entry => entry.toLowerCase() !== query.trim().toLowerCase())
  try { storage?.setItem(searchHistoryKey(storage), JSON.stringify(entries)) } catch { /* 当前页面仍可删除。 */ }
  return entries
}

export function clearSearchHistory(storage: HistoryStorage | undefined = browserStorage()): void {
  try { storage?.removeItem(searchHistoryKey(storage)) } catch { /* 不阻塞交互。 */ }
}

/** 保持原登录清理行为，同时保留按账号隔离的搜索记录。 */
export function clearAccountStorage(storage: Storage = localStorage): void {
  const keys = Array.from({ length: storage.length }, (_, index) => storage.key(index))
  for (const key of keys) {
    if (key && !key.startsWith(SEARCH_HISTORY_PREFIX)) storage.removeItem(key)
  }
}
