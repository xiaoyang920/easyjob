/**
 * 简易事件总线
 * 用于跨组件通信（如 request.ts 通知 Home.vue 弹出登录弹窗）
 */
class EventBus {
  private events: Map<string, Set<Function>> = new Map()

  on(event: string, callback: Function) {
    if (!this.events.has(event)) {
      this.events.set(event, new Set())
    }
    this.events.get(event)!.add(callback)
  }

  off(event: string, callback: Function) {
    this.events.get(event)?.delete(callback)
  }

  emit(event: string, ...args: any[]) {
    this.events.get(event)?.forEach(cb => cb(...args))
  }
}

export const eventBus = new EventBus()

/** 事件名常量 */
export const EVENT_AUTH_EXPIRED = 'auth:expired'
export const EVENT_AUTH_CHANGED = 'auth:changed'
