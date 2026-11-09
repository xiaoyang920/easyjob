import { computed, shallowRef } from 'vue'
import request from './request'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from './eventBus'
import { mergeRunOverview, readReceiptMatches, runLabel, validRun, type RunReadReceipt, type RunSnapshot, type RunStatus, type RunSummary } from './runOverview'

const snapshot = shallowRef<RunSnapshot>({ items: [], syncedAt: '' })
export const aiRunItems = computed(() => snapshot.value.items.filter(item => runLabel(item)))
export const aiRunCount = computed(() => aiRunItems.value.length)
export const aiRunConnection = shallowRef<'online' | 'reconnecting'>('online')
let owner = '', epoch = 0, started = false, timer: ReturnType<typeof setTimeout> | undefined
let syncing: Promise<void> | null = null
let retryAfter = 0, failures = 0
let viewed = '', viewedRun = '', viewedGeneration = 0
const read = new Map<string, RunReadReceipt>()
function key() { return `ai_run_notices:${owner}` }
function readKey() { return `ai_run_reads:${owner}` }
function saveReads() {
  while (read.size > 100) read.delete(read.keys().next().value!)
  try { localStorage.setItem(readKey(), JSON.stringify([...read].slice(-100))) } catch { /* Storage can be disabled. */ }
}
function mergeReads(raw: string | null) {
  const entries = JSON.parse(raw || '[]')
  if (!Array.isArray(entries)) return
  for (const entry of entries.slice(-100)) {
    if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== 'string') continue
    const [cid, receipt] = entry
    if (!receipt || typeof receipt.runId !== 'string' || !Number.isFinite(receipt.seenAt)
        || (receipt.generation !== undefined && (!Number.isInteger(receipt.generation) || receipt.generation < 0))
        || (receipt.updatedAt !== undefined && !Number.isFinite(Date.parse(receipt.updatedAt)))) continue
    const previous = read.get(cid)
    if ((previous?.seenAt ?? -1) < receipt.seenAt
        || (previous && previous.seenAt === receipt.seenAt && previous.runId === receipt.runId && !previous.updatedAt && receipt.updatedAt)) read.set(cid, receipt)
  }
}
function visible(cid: string, item?: RunSummary) {
  return viewed === cid && (!item || !viewedRun || (item.runId === viewedRun && (item.generation || 0) === viewedGeneration))
    && document.visibilityState === 'visible'
}
function acknowledge(item: RunSummary, canPinPending = false) {
  if (['running', 'awaiting_approval'].includes(item.status)) return false
  const previous = read.get(item.conversationId)
  if (previous?.runId === item.runId && (previous.generation || 0) === (item.generation || 0)) {
    if (!previous.updatedAt && !canPinPending) return false
    if (previous.status === item.status && previous.updatedAt === item.updatedAt) return false
  }
  read.delete(item.conversationId)
  read.set(item.conversationId, { runId: item.runId, status: item.status, updatedAt: item.updatedAt,
    generation: item.generation || 0, seenAt: Date.now() })
  return true
}
function reconcileRead(pollStartedAt?: number) {
  let changed = false
  snapshot.value = { ...snapshot.value, items: snapshot.value.items.map(item => {
    const receipt = read.get(item.conversationId)
    if (visible(item.conversationId, item) || readReceiptMatches(receipt, item)) {
      // Pin a live reply's pending receipt to the first matching server version.
      // A later recovery of the same run is a different, unread version.
      changed = acknowledge(item, pollStartedAt !== undefined && (receipt?.seenAt ?? 0) < pollStartedAt) || changed
      return { ...item, unread: false }
    }
    return item
  }) }
  if (changed) saveReads()
}
function save() {
  if (!owner) return
  saveReads()
  try { localStorage.setItem(key(), JSON.stringify(snapshot.value)) } catch { /* Storage can be disabled. */ }
}
function account() {
  const next = localStorage.getItem('token') ? localStorage.getItem('userId') || '' : ''
  if (next === owner) return
  owner = next; epoch++; read.clear(); syncing = null; viewed = viewedRun = ''; retryAfter = 0; failures = 0
  snapshot.value = { items: [], syncedAt: '' }
  aiRunConnection.value = 'online'
  if (!owner) return
  try { mergeReads(localStorage.getItem(readKey())) } catch { /* Ignore malformed read receipts. */ }
  try {
    const saved = JSON.parse(localStorage.getItem(key()) || 'null')
    if (Array.isArray(saved?.items) && typeof saved.syncedAt === 'string')
      snapshot.value = { syncedAt: saved.syncedAt, items: saved.items.filter(validRun).slice(0, 100) }
  } catch { /* Ignore malformed/stale local state. */ }
  reconcileRead()
}
function schedule() {
  clearTimeout(timer)
  if (!started) return
  const delay = document.visibilityState === 'visible' && snapshot.value.items.some(r => r.status === 'running') ? 3000 : 15000
  timer = setTimeout(() => { void refreshAiRuns() }, Math.max(delay, retryAfter - Date.now()))
}
export async function refreshAiRuns() {
  account()
  if (!owner) { schedule(); return }
  if (syncing) return syncing
  if (Date.now() < retryAfter) { schedule(); return }
  const version = epoch
  const pollStartedAt = Date.now()
  const job = (async () => {
    try {
      const response = await request.get('/agent/run-overview', { timeout: 10000 }) as unknown as { code: number; data: { items: RunSummary[]; serverTime: string } }
      if (version !== epoch || !localStorage.getItem('token') || localStorage.getItem('userId') !== owner) return
      if (response.code !== 200 || !Array.isArray(response.data?.items) || !Number.isFinite(Date.parse(response.data.serverTime))) throw new Error('状态获取失败')
      snapshot.value = mergeRunOverview(snapshot.value, response.data.items, response.data.serverTime)
      // A user can read a completion while an earlier poll is still in flight.
      reconcileRead(pollStartedAt)
      aiRunConnection.value = 'online'; retryAfter = 0; failures = 0; save()
    } catch (error: any) {
      if (version === epoch && owner) {
        aiRunConnection.value = 'reconnecting'
        failures++
        retryAfter = Date.now() + (error?.code === 429 ? Math.max(60000, error.retryAfterMs || 0) : Math.min(60000, 15000 * 2 ** (failures - 1)))
      }
    }
  })()
  syncing = job
  try { await job } finally { if (syncing === job) syncing = null; schedule() }
}
export function markAiRunRead(cid: string, completedRunId?: string, completedGeneration?: number) {
  account()
  if (!owner) return
  const item = snapshot.value.items.find(item => item.conversationId === cid)
  const generation = completedGeneration ?? (cid === viewed && completedRunId === viewedRun ? viewedGeneration
    : item && item.runId === completedRunId ? item.generation || 0 : 0)
  const sameVersion = !completedRunId || (!!item && item.runId === completedRunId && (item.generation || 0) === generation)
  if (completedRunId && (!item || !sameVersion || ['running', 'awaiting_approval'].includes(item.status))) {
    // The response is already visible, although the overview poll still says
    // running (or has not discovered this run). Do not mark an older run read.
    const previous = read.get(cid)
    if (previous?.runId !== completedRunId || previous.updatedAt || (previous.generation || 0) !== generation) {
      read.delete(cid); read.set(cid, { runId: completedRunId, generation, seenAt: Date.now() })
    }
  } else if (item) acknowledge(item)
  if (!item || !sameVersion) { saveReads(); return }
  snapshot.value = { ...snapshot.value, items: snapshot.value.items.map(r => r === item ? { ...r, unread: false } : r) }
  save()
}
export function setViewedAiConversation(cid: string | null, runId?: string, generation?: number) {
  account()
  const item = snapshot.value.items.find(item => item.conversationId === cid)
  if (viewed !== (cid || '') || viewedRun !== (runId || '') || generation !== undefined) viewedGeneration = generation ?? item?.generation ?? 0
  viewed = cid || ''; viewedRun = runId || ''
  if (cid && item && visible(cid, item)) markAiRunRead(cid)
}
export function trackAiRun(runId: string, cid: string, status: RunStatus = 'running', generation?: number) {
  account()
  if (!owner) return
  const existing = snapshot.value.items.find(item => item.conversationId === cid)
  const item = { runId, conversationId: cid, status, title: existing?.title || '当前对话', scope: existing?.scope,
    generation: generation ?? (existing?.runId === runId ? existing.generation || 0 : 0), updatedAt: new Date().toISOString(), unread: false }
  snapshot.value = { ...snapshot.value, items: [item, ...snapshot.value.items.filter(r => r.conversationId !== cid)].slice(0, 100) }
  save(); void refreshAiRuns()
}
export function aiConversationStatus(cid: string) { return runLabel(snapshot.value.items.find(r => r.conversationId === cid)) }
export function isAiRunRead(cid: string, runId?: string): boolean {
  const receipt = read.get(cid), item = snapshot.value.items.find(r => r.conversationId === cid)
  return !!runId && receipt?.runId === runId && (receipt.generation || 0) === (item?.generation || 0)
    && (!receipt.updatedAt || (!!item && readReceiptMatches(receipt, item)))
}
const wake = () => { void refreshAiRuns() }
const visibility = () => { if (document.visibilityState === 'visible') wake() }
const storage = (event: StorageEvent) => {
  if (event.key === 'userId' || event.key === 'token' || event.key === null) {
    const previous = owner
    account()
    if (previous !== owner) wake()
    return
  }
  if (owner && event.key === readKey() && event.newValue) {
    try { mergeReads(event.newValue); reconcileRead() } catch { /* Ignore malformed receipts from another tab. */ }
    return
  }
  if (!owner || event.key !== key() || !event.newValue) return
  // Another tab already fetched this snapshot. Consume it without another HTTP
  // request or storage write, otherwise two tabs trigger each other indefinitely.
  try {
    const saved = JSON.parse(event.newValue)
    if (!Array.isArray(saved.items) || !Number.isFinite(Date.parse(saved.syncedAt))
        || Date.parse(saved.syncedAt) < Date.parse(snapshot.value.syncedAt || '1970-01-01')) return
    snapshot.value = { syncedAt: saved.syncedAt, items: saved.items.filter(validRun).slice(0, 100).map((item: any) => ({ ...item, unread: !!item.unread })) }
    reconcileRead()
    schedule()
  } catch { /* A malformed local cache must not start a network retry. */ }
}
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
