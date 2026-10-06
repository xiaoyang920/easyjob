/** Dependency-injected renewal state machine, shared by HTTP and streaming clients. */
export function tokenExpiresSoon(token: string, now = Date.now()): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp !== 'number' || payload.exp * 1000 <= now + 60_000
  } catch { return true }
}

export function createAuthRenewal(options: {
  token: () => string | null
  user: () => string | null
  save: (token: string) => void
  renew: (token: string) => Promise<{ token: string; userId: string }>
}) {
  let pending: Promise<string | null> | null = null
  async function ensure(force = false): Promise<string | null> {
    const token = options.token()
    if (!token) return null
    if (!force && !tokenExpiresSoon(token)) return token
    if (pending) return pending
    const user = options.user()
    pending = (async () => {
      const renewed = await options.renew(token)
      // Logout/login may occur while renewal is in flight; never overwrite that state.
      if (options.token() !== token || options.user() !== user) return null
      if (String(renewed.userId) !== user || !renewed.token) throw new Error('续签账号不一致，请重新登录')
      options.save(renewed.token)
      return renewed.token
    })().finally(() => { pending = null })
    return pending
  }
  return { ensure, settled: () => pending?.then(() => {}, () => {}) || Promise.resolve() }
}
