import { test, expect, type Page } from '@playwright/test'

const routes = ['/', '/search', '/article/42', '/user-space/7', '/create-article', '/edit-article?id=42', '/draft-box', '/edit-profile', '/followers-following', '/chat', '/notifications', '/ai-chat', '/ai-memory', '/account-security', '/password-reset', '/admin']

async function mockPages(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('nickName', '测试用户')
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/user/space/7')) data = { userId: '7', nickName: '测试用户', role: 2, status: 1, followingCount: 4, followerCount: 3, articleCount: 9 }
    else if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: '文章预览', content: '<p>测试正文</p>', userId: '7', authorName: '测试用户', tags: [], canReadFull: false }
    else if (path.endsWith('/article/42/edit')) data = { articleId: '42', title: '测试草稿', content: '<p>测试正文</p>', revisionId: '10', lockVersion: 0, revisionState: 0, status: 0, tags: [] }
    else if (path.endsWith('/agent/memory')) data = { profile: { topics: [], experience: '', preferences: {} }, profile_version: '0', memories: [], extraction: { enabled: true } }
    else if (path.endsWith('/agent/library')) data = { rows: [], total: 0 }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/admin/me')) data = { userId: '7', nickName: '测试用户', permissions: ['overview.read'] }
    else if (path.endsWith('/admin/overview')) data = { users: 1, published: 0, restricted: 0, removed: 0, readingSeconds: 0, pendingReviews: 0, rules: [] }
    else if (path.endsWith('/comment/list')) data = { records: [], total: 0, pages: 1 }
    else if (/\/article\/(recommend|list|work)$|\/followers$|\/following$|\/notification\/list$/.test(path)) data = { records: [], total: 0, pages: 1 }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, status: 'success', data } })
  })
}

test('all page headers show an explicit home link and EasyJob returns home', async ({ page }) => {
  test.setTimeout(90000)
  await mockPages(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  for (const path of routes) {
    await test.step(path, async () => {
      await page.goto(path)
      const brand = page.getByRole('link', { name: 'EasyJob 首页', exact: true })
      await expect(brand).toHaveAttribute('href', '/')
      await expect(brand.locator('.logo-home')).toBeVisible()
      await expect(brand.locator('.logo-text')).toBeVisible()
      if (path === '/') await expect(brand).toHaveAttribute('aria-current', 'page')
      else {
        await expect(brand).not.toHaveAttribute('aria-current', 'page')
        await brand.locator('.logo-text').click()
        await expect(page).toHaveURL(/\/$/)
      }
    })
  }
  expect(errors).toEqual([])
})

test('home label supports clicking and keyboard navigation', async ({ page }) => {
  await mockPages(page)
  await page.goto('/draft-box')
  await page.getByRole('link', { name: 'EasyJob 首页', exact: true }).locator('.logo-home').click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/ai-chat')
  const brand = page.getByRole('link', { name: 'EasyJob 首页', exact: true })
  await brand.focus()
  await page.screenshot({ path: '../logs/home-brand-desktop.png', animations: 'disabled' })
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('link', { name: 'EasyJob 首页', exact: true })).toBeVisible()
  await page.screenshot({ path: '../logs/home-brand-preview.png', clip: { x: 0, y: 0, width: 440, height: 110 }, animations: 'disabled' })
})

test('the home entry stays visible and clear of other controls on narrow screens', async ({ browser, baseURL }) => {
  test.setTimeout(90000)
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  try {
    const page = await context.newPage()
    await mockPages(page)
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 })
      for (const path of routes) {
        await test.step(`${width}px ${path}`, async () => {
          await page.goto(path)
          const brand = page.getByRole('link', { name: 'EasyJob 首页', exact: true })
          const label = brand.locator('.logo-home')
          await expect(label).toBeVisible()
          const bounds = (await brand.boundingBox())!
          expect(bounds.x).toBeGreaterThanOrEqual(0)
          expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
          // Hit testing catches links covered by a search box or adjacent navigation.
          await expect(label).toBeInViewport()
          await label.tap({ trial: true })
        })
      }
    }
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/ai-chat')
    await expect(page.getByRole('link', { name: 'EasyJob 首页', exact: true })).toBeVisible()
    await page.screenshot({ path: '../logs/home-brand-mobile.png', animations: 'disabled' })
    await page.getByRole('link', { name: 'EasyJob 首页', exact: true }).tap()
    await expect(page).toHaveURL(/\/$/)
  } finally { await context.close() }
})
