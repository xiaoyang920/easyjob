export type GrowthActivity = {
  activityId: string; title: string; coinPrice: number; growthSeconds: number;
  availableStock: number; totalStock: number; startsAt: string; endsAt: string;
  state: 'DRAFT' | 'ACTIVE' | 'PAUSED'; paySeconds: number;
}
export type GrowthOrder = {
  orderId: string; activityId: string; coinCost: number; growthSeconds: number;
  state: 'PENDING' | 'PAID' | 'CLOSED' | 'REJECTED'; expiresAt: string; reason: string;
}
export type GrowthAudit = {
  activity: GrowthActivity; databaseStockConsistent: boolean; redisStock: string | null;
  unconfirmedReservations: number; pendingEffects: number; missingReceipts: boolean;
  ordersByState: { state: string; amount: number }[];
}
export function activityStatus(activity: GrowthActivity, now: number) {
  if (activity.state === 'DRAFT') return '草稿'
  if (now >= Date.parse(activity.endsAt)) return '已结束'
  if (activity.state === 'PAUSED') return '已下架'
  if (now < Date.parse(activity.startsAt)) return '即将开始'
  return activity.availableStock <= 0 ? '已售罄' : '兑换中'
}
export function orderStatus(state: string) {
  return ({ ACCEPTED: '正在确认', PENDING: '待支付', PAID: '已支付，成长已到账', CLOSED: '已关闭', REJECTED: '未抢到' } as Record<string, string>)[state] || state
}
export function growthTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
export function localDateTime(date: Date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
export function auditReady(audit: GrowthAudit) {
  return audit.databaseStockConsistent && !audit.missingReceipts && audit.unconfirmedReservations === 0
    && audit.pendingEffects === 0 && audit.redisStock !== null && Number(audit.redisStock) === audit.activity.availableStock
}
