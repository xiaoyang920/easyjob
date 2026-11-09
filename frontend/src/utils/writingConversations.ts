// Only the association lives in this browser. Messages and run progress stay on the server.
export function writingConversationKey(owner: string | null, scope: string) {
  return owner && scope ? `easyjob:writing-conversation:${encodeURIComponent(owner)}:${encodeURIComponent(scope)}` : ''
}
export function writingBindingKey(owner: string | null, scope: string) { return writingConversationKey(owner, scope).replace('writing-conversation:', 'writing-conversation-bound:') }
export function rememberNewWritingTopic(storage: Storage, owner: string | null, scope: string, fresh: boolean) {
  const key = writingConversationKey(owner, scope).replace('writing-conversation:', 'writing-topic-new:')
  if (!owner || !scope) return
  try { if (fresh) storage.setItem(key, '1'); else storage.removeItem(key) } catch { /* Content remains server-side. */ }
}
export function hasNewWritingTopic(storage: Storage, owner: string | null, scope: string) {
  try { return !!owner && storage.getItem(writingConversationKey(owner, scope).replace('writing-conversation:', 'writing-topic-new:')) === '1' } catch { return false }
}
export function knownWritingConversations(storage: Storage, owner: string | null) {
  const prefix = writingConversationKey(owner, 'new').replace(/new$/, '')
  if (!owner || !prefix) return []
  const entries: { scope: string; id: string }[] = []
  try {
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index)
      if (!key?.startsWith(prefix)) continue
      const scope = decodeURIComponent(key.slice(prefix.length)), id = storage.getItem(key)
      if ((scope === 'new' || /^[1-9]\d*$/.test(scope)) && id && /^[1-9]\d*$/.test(id)
          && storage.getItem(writingBindingKey(owner, scope)) !== id) entries.push({ scope, id })
    }
  } catch { /* Leave browser associations intact if storage is unavailable. */ }
  return entries.slice(0, 100)
}
export function readWritingConversation(storage: Storage, owner: string | null, scope: string): string | null {
  try {
    const key = writingConversationKey(owner, scope), id = key ? storage.getItem(key) : null
    return id && id.length <= 128 && id.trim() === id ? id : null
  } catch { return null }
}
export function saveWritingConversation(storage: Storage, owner: string | null, scope: string, id: string | null) {
  const key = writingConversationKey(owner, scope)
  if (!key) return false
  try {
    if (id) storage.setItem(key, id)
    else { storage.removeItem(key); storage.removeItem(writingBindingKey(owner, scope)) }
    return true
  } catch { return false }
}
export function migrateWritingConversation(storage: Storage, owner: string | null, previous: string, scope: string, activeId: string | null) {
  const id = activeId || readWritingConversation(storage, owner, previous)
  if (id && !saveWritingConversation(storage, owner, scope, id)) return false
  if (!id && hasNewWritingTopic(storage, owner, previous)) rememberNewWritingTopic(storage, owner, scope, true)
  rememberNewWritingTopic(storage, owner, previous, false)
  return saveWritingConversation(storage, owner, previous, null)
}
