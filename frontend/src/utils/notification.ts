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

/**
 * 建立 SSE 连接。多次调用幂等，已连接时直接返回。
 * EventSource 不支持自定义 Header，所以 token 随 URL query 传；后端 /api/notification/stream 需要支持 ?token=xxx 鉴权，
 * 或者在 Nginx 同源 + Cookie 鉴权场景下省略该参数。
 */
export async function connectNotifyStream() {
  if (eventSource) return
  let token: string | null
  try { token = await ensureAccessToken() } catch { return }
  if (eventSource) return
  if (!token) return

  const url = `/api/notification/stream?token=${encodeURIComponent(token)}`
  try {
    eventSource = new EventSource(url)
  } catch (e) {
    console.error('[notify] SSE 建连失败', e)
    return
  }

  eventSource.addEventListener('notification', (e: MessageEvent) => {
    try {
      const msg: NotifyMessage = JSON.parse(e.data)
      latestNotify.value = msg
      notifyUnreadCount.value += 1
    } catch (err) {
      console.error('[notify] 解析消息失败', err, e.data)
    }
  })
  eventSource.addEventListener('connected', () => { void fetchNotifyUnreadCount() })

  eventSource.onerror = () => {
    // 浏览器 EventSource 会自动重连，这里只在完全断开时做兜底重连
    if (eventSource) {
      closeNotifyStream()
      if (!reconnectTimer) {
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = null
          connectNotifyStream()
        }, 5000)
      }
    }
  }
}

/** 主动断开（登出时调用） */
export function closeNotifyStream() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

/** 拉取未读数（登录后初始化 + 断线重连后对齐） */
export async function fetchNotifyUnreadCount() {
  try {
    const res: any = await request.get('/notification/unread-count')
    notifyUnreadCount.value = Number(res.data) || 0
  } catch (e) {
    console.error('[notify] 拉取未读数失败', e)
  }
}

/** 重置本地状态（登出时用） */
export function resetNotifyState() {
  notifyUnreadCount.value = 0
  latestNotify.value = null
}
