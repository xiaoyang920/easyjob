export type RunStatus = 'running' | 'awaiting_approval' | 'succeeded' | 'failed' | 'expired' | 'cancelled'
export type RunScope = 'general' | 'article' | 'writing'
export interface RunSummary { runId: string; conversationId: string; title: string; status: RunStatus; updatedAt: string; scope?: RunScope; generation?: number }
export interface RunNotice extends RunSummary { unread: boolean }
export interface RunSnapshot { items: RunNotice[]; syncedAt: string }
export interface RunReadReceipt { runId: string; status?: RunStatus; updatedAt?: string; generation?: number; seenAt: number }
const statuses: RunStatus[] = ['running', 'awaiting_approval', 'succeeded', 'failed', 'expired', 'cancelled']
export function validRun(value: any): value is RunSummary {
  return value && typeof value.runId === 'string' && typeof value.conversationId === 'string'
    && typeof value.title === 'string' && typeof value.updatedAt === 'string' && statuses.includes(value.status)
    && (value.scope === undefined || ['general', 'article', 'writing'].includes(value.scope))
    && (value.generation === undefined || (Number.isInteger(value.generation) && value.generation >= 0))
}
export function mergeRunOverview(previous: RunSnapshot, incoming: RunSummary[], serverTime: string): RunSnapshot {
  const known = new Map(previous.items.map(item => [item.conversationId, item]))
  return { syncedAt: serverTime, items: incoming.filter(validRun).map(item => {
    const old = known.get(item.conversationId)
    const terminal = !['running', 'awaiting_approval'].includes(item.status)
    const changed = old?.runId !== item.runId || old?.status !== item.status || old?.updatedAt !== item.updatedAt
      || (old?.generation || 0) !== (item.generation || 0)
    // First-time visits do not flag every old answer as unread. Tracked active
    // runs that finished while the page was closed still create a notification.
    const recent = !!previous.syncedAt && Date.parse(item.updatedAt) > Date.parse(previous.syncedAt)
    return { ...item, unread: terminal && ((changed && (!!old || recent)) || (!changed && !!old?.unread)) }
  }) }
}
export function readReceiptMatches(receipt: RunReadReceipt | undefined, item: RunSummary): boolean {
  return !!receipt && receipt.runId === item.runId && !['running', 'awaiting_approval'].includes(item.status)
    && (receipt.generation || 0) === (item.generation || 0)
    && (!receipt.status || receipt.status === item.status) && (!receipt.updatedAt || receipt.updatedAt === item.updatedAt)
}
export function runCategory(item: RunSummary): string {
  return item.scope === 'writing' ? '草稿写作' : item.scope === 'article' ? '文章问答' : '普通聊天'
}
export function runLabel(item?: RunNotice): string {
  if (!item) return ''
  if (item.status === 'running') return '正在生成'
  if (item.status === 'awaiting_approval') return '等待确认'
  if (!item.unread) return ''
  return item.status === 'succeeded' ? '有新回复' : item.status === 'cancelled' ? '已停止' : '生成中断'
}
