import { createAuthRenewal } from './authRenewal'
import { clearAccountStorage } from './searchHistory'
import { eventBus, EVENT_AUTH_EXPIRED } from './eventBus'

class SessionExpired extends Error {}
let logoutPending: Promise<void> | null = null

export function expireSession(token: string | null) {
  if (!token || localStorage.getItem('token') !== token) return
  clearAccountStorage()
  eventBus.emit(EVENT_AUTH_EXPIRED)
}

const renewal = createAuthRenewal({
  token: () => localStorage.getItem('token'),
  user: () => localStorage.getItem('userId'),
  save: token => localStorage.setItem('token', token),
  renew: async token => {
    const response = await fetch('/api/auth/refresh', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Authorization': `Bearer ${token}`, 'X-Auth-Refresh': '1' },
      signal: AbortSignal.timeout(10_000)
    })
    const body = await response.json()
    if (response.status === 401 || body.code === 401) throw new SessionExpired('登录已过期，请重新登录')
    if (!response.ok || body.code !== 200) throw new Error(body.message || '续签暂不可用，请稍后重试')
    return body.data
  }
})

export async function ensureAccessToken(force = false) {
  const token = localStorage.getItem('token')
  try { return await renewal.ensure(force) }
  catch (error) {
    // Network/service errors retain credentials; only an explicit auth rejection signs out.
    if (error instanceof SessionExpired) expireSession(token)
    throw error
  }
}

export async function recoverAccessToken(rejected: string | null, user: string | null) {
  if (!rejected || !localStorage.getItem('token') || localStorage.getItem('userId') !== user) return null
  if (localStorage.getItem('token') !== rejected) return localStorage.getItem('token')
  return ensureAccessToken(true)
}

/** Replay only a rejected handshake, never restart an already-open SSE stream. */
export async function authenticatedFetch(url: string, init: RequestInit) {
  const user = localStorage.getItem('userId')
  let token = await ensureAccessToken()
  const send = () => {
    if (localStorage.getItem('userId') !== user) throw new Error('登录账号已改变，请重新操作')
    const headers = new Headers(init.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    else headers.delete('Authorization')
    return fetch(url, { ...init, headers })
  }
  let response = await send()
  if (response.status === 401) {
    token = await recoverAccessToken(token, user)
    if (token) response = await send()
    if (response.status === 401) expireSession(token)
  }
  return response
}

export async function waitForLogout() {
  await logoutPending
  await renewal.settled()
}

export function signOutSession(): Promise<void> {
  if (logoutPending) return logoutPending
  clearAccountStorage()
  logoutPending = renewal.settled().then(() => fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin',
    headers: { 'X-Auth-Refresh': '1' }, signal: AbortSignal.timeout(10_000) })
  )
    .then(response => response.json()).then(body => {
      if (body.code !== 200) throw new Error('退出登录未完成，请重试')
    }).finally(() => { logoutPending = null })
  return logoutPending
}

export function startAuthRenewal() {
  // Also migrates valid old seven-day JWTs into revocable browser sessions.
  void ensureAccessToken(true).catch(() => {})
  let lastActivity = Date.now()
  const check = () => {
    if (document.visibilityState === 'visible' && Date.now() - lastActivity < 300_000)
      void ensureAccessToken().catch(() => {})
  }
  const active = () => { lastActivity = Date.now(); check() }
  const touch = () => { lastActivity = Date.now() }
  window.addEventListener('focus', active)
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') active() })
  document.addEventListener('pointerdown', touch, { passive: true })
  document.addEventListener('keydown', touch)
  document.addEventListener('scroll', touch, { passive: true, capture: true })
  window.setInterval(check, 60_000)
}
