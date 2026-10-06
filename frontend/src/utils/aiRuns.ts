import { computed, shallowRef } from 'vue'
import request from './request'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from './eventBus'
import { mergeRunOverview, runLabel, validRun, type RunSnapshot, type RunStatus, type RunSummary } from './runOverview'

const snapshot = shallowRef<RunSnapshot>({ items: [], syncedAt: '' })
export const aiRunItems = computed(() => snapshot.value.items.filter(item => runLabel(item)))
export const aiRunCount = computed(() => aiRunItems.value.length)
export const aiRunConnection = shallowRef<'online' | 'reconnecting'>('online')
let owner = '', epoch = 0, started = false, timer: ReturnType<typeof setTimeout> | undefined
let syncing: Promise<void> | null = null
let viewed = ''
const read = new Map<string, string>()
function key() { return `ai_run_notices:${owner}` }
function save() {
  if (!owner) return
  try { localStorage.setItem(key(), JSON.stringify(snapshot.value)) } catch { /* Storage can be disabled. */ }
}
function account() {
  const next = localStorage.getItem('token') ? localStorage.getItem('userId') || '' : ''
  if (next === owner) return
  owner = next; epoch++; read.clear(); syncing = null; viewed = ''
  snapshot.value = { items: [], syncedAt: '' }
  aiRunConnection.value = 'online'
  if (!owner) return
  try {
    const saved = JSON.parse(localStorage.getItem(key()) || 'null')
    if (Array.isArray(saved?.items) && typeof saved.syncedAt === 'string')
      snapshot.value = { syncedAt: saved.syncedAt, items: saved.items.filter(validRun).slice(0, 100) }
  } catch { /* Ignore malformed/stale local state. */ }
}
function schedule() {
  clearTimeout(timer)
  if (!started) return
  const delay = document.visibilityState === 'visible' && snapshot.value.items.some(r => r.status === 'running') ? 3000 : 15000
  timer = setTimeout(() => { void refreshAiRuns() }, delay)
}
export async function refreshAiRuns() {
  account()
  if (!owner) { schedule(); return }
  if (syncing) return syncing
  const version = epoch
  const job = (async () => {
    try {
      const response = await request.get('/agent/run-overview', { timeout: 10000 }) as unknown as { code: number; data: { items: RunSummary[]; serverTime: string } }
      if (version !== epoch || !localStorage.getItem('token') || localStorage.getItem('userId') !== owner) return
      if (response.code !== 200 || !Array.isArray(response.data?.items) || !Number.isFinite(Date.parse(response.data.serverTime))) throw new Error('状态获取失败')
      snapshot.value = mergeRunOverview(snapshot.value, response.data.items, response.data.serverTime)
      // A user can read a completion while an earlier poll is still in flight.
      for (const item of snapshot.value.items) if (item.conversationId === viewed || read.get(item.conversationId) === `${item.runId}:${item.status}`) item.unread = false
      aiRunConnection.value = 'online'; save()
    } catch {
      if (version === epoch && owner) aiRunConnection.value = 'reconnecting'
    }
  })()
  syncing = job
  try { await job } finally { if (syncing === job) syncing = null; schedule() }
}
export function markAiRunRead(cid: string) {
  const item = snapshot.value.items.find(item => item.conversationId === cid)
  if (!item) return
  read.set(cid, `${item.runId}:${item.status}`)
  snapshot.value = { ...snapshot.value, items: snapshot.value.items.map(r => r === item ? { ...r, unread: false } : r) }
  save()
}
export function setViewedAiConversation(cid: string | null) {
  account(); viewed = cid || ''
  if (cid) markAiRunRead(cid)
}
export function trackAiRun(runId: string, cid: string, status: RunStatus = 'running') {
  account()
  if (!owner) return
  const existing = snapshot.value.items.find(item => item.conversationId === cid)
  const item = { runId, conversationId: cid, status, title: existing?.title || '当前对话', updatedAt: new Date().toISOString(), unread: false }
  snapshot.value = { ...snapshot.value, items: [item, ...snapshot.value.items.filter(r => r.conversationId !== cid)].slice(0, 100) }
  save(); void refreshAiRuns()
}
export function aiConversationStatus(cid: string) { return runLabel(snapshot.value.items.find(r => r.conversationId === cid)) }
const wake = () => { void refreshAiRuns() }
const visibility = () => { if (document.visibilityState === 'visible') wake() }
const storage = (event: StorageEvent) => { if (event.key === 'userId' || event.key === 'token' || event.key === key()) { account(); wake() } }
export function startAiRunMonitor() {
  if (started) return
  started = true
  eventBus.on(EVENT_AUTH_CHANGED, wake); eventBus.on(EVENT_AUTH_EXPIRED, wake)
  window.addEventListener('focus', wake); window.addEventListener('storage', storage)
  document.addEventListener('visibilitychange', visibility)
  wake()
}
export function stopAiRunMonitor() {
  started = false; epoch++; clearTimeout(timer); syncing = null
  eventBus.off(EVENT_AUTH_CHANGED, wake); eventBus.off(EVENT_AUTH_EXPIRED, wake)
  window.removeEventListener('focus', wake); window.removeEventListener('storage', storage)
  document.removeEventListener('visibilitychange', visibility)
}
