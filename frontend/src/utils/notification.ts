import { ref } from 'vue'
import request from './request'
import { ensureAccessToken } from './authSession'

/**
 * 通知消息体（对应后端 NotificationMessage DTO）
 */
export interface NotifyMessage {
  notificationId: number | string
  userId: number | string
  senderId: number | string
  senderNickname?: string
  senderAvatar?: string
  type: number // 1评论/回复 2点赞 3收藏 4关注 5系统 6审核通过 7审核驳回
  articleId?: number | string | null
  articleTitle?: string | null
  targetId?: number | string | null
  targetPreview?: string | null
  content: string
  isRead?: number
  createTime?: string
}

/** 全局未读数，响应式，导航栏 / 通知页共用 */
export const notifyUnreadCount = ref(0)

/** 最新一条通知（用于 toast / 首页消息刷新） */
export const latestNotify = ref<NotifyMessage | null>(null)

let eventSource: EventSource | null = null
let reconnectTimer: number | null = null
let generation = 0, failures = 0
let unreadPending: Promise<void> | null = null, unreadOwner = ''

/**
 * 建立 SSE 连接。多次调用幂等，已连接时直接返回。
 * EventSource 不支持自定义 Header，所以 token 随 URL query 传；后端 /api/notification/stream 需要支持 ?token=xxx 鉴权，
 * 或者在 Nginx 同源 + Cookie 鉴权场景下省略该参数。
 */
export async function connectNotifyStream() {
  if (eventSource || reconnectTimer) return
  const version = generation, owner = localStorage.getItem('userId')
  if (!owner) return
  let token: string | null
  try { token = await ensureAccessToken() } catch { return }
  if (eventSource || reconnectTimer || version !== generation || localStorage.getItem('userId') !== owner) return
  if (!token || !localStorage.getItem('token')) return

  const url = `/api/notification/stream?token=${encodeURIComponent(token)}`
  let source: EventSource
  try {
    source = new EventSource(url)
    eventSource = source
  } catch (e) {
    console.error('[notify] SSE 建连失败', e)
    return
  }

  source.addEventListener('notification', (e: MessageEvent) => {
    if (eventSource !== source || localStorage.getItem('userId') !== owner) return
    try {
      const msg: NotifyMessage = JSON.parse(e.data)
      latestNotify.value = msg
      notifyUnreadCount.value += 1
    } catch (err) {
      console.error('[notify] 解析消息失败', err, e.data)
    }
  })
  let openedAt = Date.now()
  source.addEventListener('connected', () => { openedAt = Date.now(); void fetchNotifyUnreadCount() })

  source.onerror = () => {
    if (eventSource !== source) return
    if (Date.now() - openedAt > 30000) failures = 0
    failures++
    closeNotifyStream(false)
    // One reconnect owner, with bounded exponential backoff. Page mounts must
    // not bypass this timer and a stale source must not close its replacement.
    const delay = Math.min(60000, 5000 * 2 ** Math.min(failures - 1, 4))
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      void connectNotifyStream()
    }, delay)
  }
}

/** 主动断开（登出时调用） */
export function closeNotifyStream(resetBackoff = true) {
  generation++
  if (resetBackoff) failures = 0
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

/** 拉取未读数（登录后初始化 + 断线重连后对齐） */
export async function fetchNotifyUnreadCount() {
  const owner = localStorage.getItem('userId')
  if (!owner || !localStorage.getItem('token')) return
  if (unreadPending && unreadOwner === owner) return unreadPending
  unreadOwner = owner
  const job = (async () => {
    try {
      const res: any = await request.get('/notification/unread-count')
      if (localStorage.getItem('userId') === owner && localStorage.getItem('token')) notifyUnreadCount.value = Number(res.data) || 0
    } catch (e) { console.error('[notify] 拉取未读数失败', e) }
  })()
  unreadPending = job
  try { await job } finally { if (unreadPending === job) unreadPending = null }
}

/** 重置本地状态（登出时用） */
export function resetNotifyState() {
  notifyUnreadCount.value = 0
  latestNotify.value = null
}
