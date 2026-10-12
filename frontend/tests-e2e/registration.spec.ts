import { test, expect, type Page } from '@playwright/test'

// Exercise the real forms and navigation with isolated APIs; no real users or emails are created.
async function setup(page: Page, fail = false) {
  const identity = { token: 'qa.' + Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url') + '.test',
    userId: '9007199254740993', nickName: '新读者', email: 'register@example.invalid', avatar: null }
  const calls: string[] = []
  const submitted: any[] = []
  await page.routeWebSocket('**/ws/**', () => {})
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    calls.push(url.pathname)
    let data: any = []
    if (url.pathname === '/api/auth/register') {
      submitted.push(request.postDataJSON())
      if (fail) return route.fulfill({ json: { code: 400, status: 'error', message: '验证码错误' } })
      return route.fulfill({ headers: { 'Set-Cookie': 'easyjob_refresh=isolated-test; HttpOnly; SameSite=Strict; Path=/api/auth' },
        json: { code: 200, status: 'success', data: identity } })
    }
    if (url.pathname === '/api/auth/refresh') data = { token: identity.token, userId: identity.userId }
    else if (url.pathname.includes('/user/space/')) data = { ...identity, articleCount: 0, followerCount: 0, followingCount: 0 }
    else if (url.pathname.includes('/article/detail/')) data = { articleId: '700', title: '注册体验测试文章', content: '<p>保持当前阅读位置。</p>',
      authorId: '1', authorName: '作者', requiredLevel: 0, likeCount: 0, collectCount: 0 }
    else if (url.pathname.includes('/comment/')) data = { list: [], total: 0 }
    else if (url.pathname === '/api/article/work' || url.pathname === '/api/article/recommend' || url.pathname === '/api/article/list')
      data = { records: [], total: 0, pages: 1 }
    else if (url.pathname.endsWith('/total-unread-count') || url.pathname.endsWith('/unread-count')) data = 0
    else if (url.pathname === '/api/agent/run-overview') data = { items: [], serverTime: new Date().toISOString() }
    else if (url.pathname === '/api/notification/stream')
      return route.fulfill({ contentType: 'text/event-stream', body: ': isolated test\n\n' })
    return route.fulfill({ json: { code: 200, status: 'success', data } })
  })
  return { identity, calls, submitted }
}

async function register(page: Page) {
  const form = page.locator('.register-form')
  await expect(form).toBeVisible()
  await form.getByPlaceholder('请输入昵称', { exact: true }).fill('新读者')
  await form.getByPlaceholder('请输入邮箱地址', { exact: true }).fill('register@example.invalid')
  await form.getByPlaceholder('请输入邮箱验证码', { exact: true }).fill('123456')
  await form.getByPlaceholder('请输入密码', { exact: true }).fill('test-password')
  await form.getByPlaceholder('请再次输入密码', { exact: true }).fill('test-password')
  await form.getByRole('button', { name: '注册', exact: true }).click()
}

test('homepage registration logs in immediately and survives refresh without another login request', async ({ page, context }) => {
  const { calls, submitted, identity } = await setup(page)
  await page.goto('/?register=true')
  await register(page)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '账户菜单', exact: true })).toBeVisible()
  await expect(page.getByText('注册成功，已自动登录', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('userId'))).toBe(identity.userId)
  expect(submitted).toEqual([{ nickName: '新读者', email: 'register@example.invalid', code: '123456', password: 'test-password' }])
  const cookie = (await context.cookies()).find(cookie => cookie.name === 'easyjob_refresh')
  expect(cookie?.httpOnly).toBe(true)
  await page.reload()
  await expect(page.getByRole('button', { name: '账户菜单', exact: true })).toBeVisible()
  expect(calls).toContain('/api/auth/refresh')
  expect(calls.filter(path => path === '/api/auth/register')).toHaveLength(1)
  expect(calls.some(path => path === '/api/auth/login' || path === '/api/auth/login-by-email')).toBe(false)
})

test('registration resumes the page that required authentication', async ({ page }) => {
  await setup(page)
  await page.goto('/?login=true&redirect=%2Fdraft-box')
  await page.locator('.login-form').getByText('立即注册', { exact: true }).click()
  await register(page)
  await expect(page).toHaveURL(/\/draft-box$/)
  await expect(page.getByRole('button', { name: '账户菜单', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('direct registration link preserves its redirect target', async ({ page }) => {
  await setup(page)
  await page.goto('/?register=true&redirect=%2Fdraft-box')
  await register(page)
  await expect(page).toHaveURL(/\/draft-box$/)
})

test('article registration stays on the article and refreshes the authenticated details', async ({ page }) => {
  const { calls, identity } = await setup(page)
  await page.goto('/article/700')
  await expect(page.getByRole('heading', { name: '注册体验测试文章', exact: true })).toBeVisible()
  await page.locator('.like-btn').first().click()
  await page.locator('.login-form').getByText('立即注册', { exact: true }).click()
  await register(page)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('注册成功，已自动登录', { exact: true })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/article/700')
  expect(await page.evaluate(() => localStorage.getItem('userId'))).toBe(identity.userId)
  await expect.poll(() => calls.filter(path => path === '/api/article/detail/700').length).toBeGreaterThanOrEqual(2)
  expect(calls).not.toContain('/api/auth/login')
})

test('registration errors keep form input and never create a local login state', async ({ page }) => {
  await setup(page, true)
  await page.goto('/?register=true')
  await register(page)
  await expect(page.getByText('验证码错误', { exact: true })).toBeVisible()
  await expect(page.locator('.register-form')).toBeVisible()
  await expect(page.locator('.register-form').getByPlaceholder('请输入昵称', { exact: true })).toHaveValue('新读者')
  expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull()
  await expect(page.getByRole('button', { name: '账户菜单', exact: true })).toHaveCount(0)
})
