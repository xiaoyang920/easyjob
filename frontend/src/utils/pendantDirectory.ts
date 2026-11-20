import { shallowReactive } from 'vue'

const batchSize = 50
const cacheTime = 60_000
const entries = shallowReactive(new Map<string, { url?: string, expires: number }>())
const pending = new Set<string>()
const loading = new Set<string>()
let timer: ReturnType<typeof setTimeout> | undefined

function userKey(userId?: string | number | null) {
  if (typeof userId === 'number' && !Number.isSafeInteger(userId)) return ''
  const id = String(userId ?? '')
  return /^[1-9]\d{0,18}$/.test(id) ? id : ''
}

export function getPendant(userId?: string | number | null) {
  return entries.get(userKey(userId))?.url
}

/** Update all mounted surfaces as soon as an equip/remove request succeeds. */
export function rememberPendant(userId: string | number | null | undefined, url?: string) {
  const id = userKey(userId)
  if (id) entries.set(id, { url, expires: Date.now() + cacheTime })
}

export function requestPendant(userId?: string | number | null) {
  const id = userKey(userId)
  if (!id || loading.has(id) || (entries.get(id)?.expires ?? 0) > Date.now()) return
  pending.add(id)
  if (timer === undefined) timer = setTimeout(flush, 12)
}

function flush() {
  timer = undefined
  const ids = [...pending]
  pending.clear()
  for (let at = 0; at < ids.length; at += batchSize) void loadBatch(ids.slice(at, at + batchSize))
}

async function loadBatch(ids: string[]) {
  const previous = new Map(ids.map(id => [id, entries.get(id)]))
  ids.forEach(id => loading.add(id))
  try {
    const response = await fetch('/api/user/space/pendants?ids=' + ids.join(','), { signal: AbortSignal.timeout(6000) })
    if (!response.ok) return
    const body = await response.json()
    if (body.code !== 200 || !body.data || typeof body.data !== 'object' || Array.isArray(body.data)) return
    for (const id of ids) {
      // A recent equip/remove wins over an earlier directory request.
      if (previous.get(id) !== entries.get(id)) continue
      const url = body.data[id]
      rememberPendant(id, typeof url === 'string' && url.startsWith('/uploads/') ? url : undefined)
    }
  } catch {
    // The portrait remains visible when decoration data is temporarily unavailable.
  } finally {
    ids.forEach(id => loading.delete(id))
  }
}
