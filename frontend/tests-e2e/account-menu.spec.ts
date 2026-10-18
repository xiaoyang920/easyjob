import { test, expect, type Page } from '@playwright/test'

async function account(page: Page, role = 1, status = 1) {
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('nickName', '大b')
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/user/space/7')) data = { role, status, followingCount: 4, followerCount: 3, articleCount: 9, readingProgress: { level: 4 } }
    else if (path.endsWith('/agent/library')) data = { rows: [], total: 0 }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/chat/total-unread-count') || path.endsWith('/notify/unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat')
}

test('account popover keeps personal settings while the avatar stays anchored during hover', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 }); await account(page)
  const avatar = page.getByRole('button', { name: '账户菜单', exact: true })
  const before = await avatar.boundingBox()
  await avatar.hover()
  const panel = page.locator('#app-account-panel')
  await expect(panel.getByRole('link', { name: '编辑资料', exact: true })).toBeVisible()
  await expect(panel.getByLabel('阅读等级 L4')).toBeVisible()
  await expect(panel.locator('.app-account-items a')).toHaveText(['编辑资料', '账号安全'])
  await expect(panel.locator('.app-account-stats a')).toHaveCount(3)
  await expect(page.locator('.app-nav-links .app-nav-link')).toHaveCount(6)
  await expect(panel.locator('a[href="/"],a[href="/draft-box"],a[href="/chat"],a[href="/notifications"],a[href="/ai-chat"],a[href="/ai-memory"],a[href="/create-article"]')).toHaveCount(0)
  await expect(panel.getByRole('link', { name: '大b的个人空间', exact: true })).toHaveAttribute('href', '/user-space')
  const after = await avatar.boundingBox()
  expect(after).toEqual(before)
  await panel.locator('.app-account-stats').hover(); await expect(panel).toBeVisible()
  await avatar.hover(); await expect(panel).toBeVisible()
  await page.mouse.move(10, 400); await expect(panel).toHaveCount(0)
})

test('administrator entry is retained and keyboard closing works with the compact card', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 }); await account(page, 2)
  const avatar = page.getByRole('button', { name: '账户菜单', exact: true })
  await avatar.focus(); await page.keyboard.press('ArrowDown')
  const panel = page.locator('#app-account-panel')
  await expect(panel.getByRole('link', { name: '管理后台', exact: true })).toBeVisible()
  await expect(panel.locator('.app-account-items a')).toHaveText(['编辑资料', '账号安全', '管理后台'])
  await expect(panel.getByRole('button', { name: '退出登录', exact: true })).toBeVisible()
  await page.screenshot({ path: '../logs/account-menu-desktop.png', animations: 'disabled' })
  await page.screenshot({ path: '../logs/account-menu-preview.png', clip: { x: 840, y: 0, width: 420, height: 530 }, animations: 'disabled' })
  await page.keyboard.press('Escape'); await expect(panel).toHaveCount(0)
})

test('touch account card fits the screen and hides administrator controls for inactive accounts', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  try {
    const page = await context.newPage(); await account(page, 2, 0)
    await page.getByRole('button', { name: '账户菜单', exact: true }).tap()
    const panel = page.locator('#app-account-panel')
    await expect(panel.getByRole('link', { name: '账号安全', exact: true })).toBeVisible()
    await expect(panel.getByRole('link', { name: '管理后台', exact: true })).toHaveCount(0)
    const bounds = await panel.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844)
    await page.screenshot({ path: '../logs/account-menu-mobile.png', animations: 'disabled' })
    await page.getByRole('button', { name: '账户菜单', exact: true }).tap()
    await expect(panel).toHaveCount(0)
  } finally { await context.close() }
})
