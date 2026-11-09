import { test, expect, type Page } from '@playwright/test'

const aid = '496effca-5f29-420e-b7ba-821ed893dc44'
const activity = (state = 'ACTIVE') => ({ activityId: aid, title: '周末阅读成长专场', coinPrice: 10, growthSeconds: 1800, totalStock: 100, availableStock: 98, startsAt: new Date(Date.now() - 60000).toISOString(), endsAt: new Date(Date.now() + 3600000).toISOString(), state, paySeconds: 120 })
async function setup(page: Page, role = 2) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => { localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`); localStorage.setItem('userId', '7'); localStorage.setItem('nickName', '商城用户') })
  const state = { rows: [activity()], writes: [] as { path: string; data: any }[], adminReads: 0, failPublish: false, failWallet: false }
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname
    let data: any = null, code = 200, message = '操作成功'
    if (path === '/api/admin/me') data = { userId: '7', role, permissions: ['overview.read', 'articles.read', 'reviews.read'] }
    else if (path === '/api/admin/overview') data = { users: 10, published: 5, rules: [] }
    else if (path === '/api/user/space/7') data = { userId: '7', role, status: 1, followingCount: 4, followerCount: 2, articleCount: 13, readingProgress: { level: 4 } }
    else if (path === '/api/growth/admin/activities' && req.method() === 'GET') { state.adminReads++; data = state.rows }
    else if (path === '/api/growth/admin/activities' && req.method() === 'POST') {
      const body = req.postDataJSON(); state.writes.push({ path, data: body }); const row = { ...activity('DRAFT'), ...body }; state.rows = [row]; data = row
    }
    else if (/\/growth\/admin\/activities\/.+\/(activate|pause|resume)$/.test(path)) {
      state.writes.push({ path, data: null })
      if (path.endsWith('/activate') && state.failPublish) { code = 503; message = '活动状态暂不可用' }
      else { state.rows[0]!.state = path.endsWith('/pause') ? 'PAUSED' : 'ACTIVE'; data = state.rows[0] }
    }
    else if (path.endsWith('/audit')) data = { activity: state.rows[0], databaseStockConsistent: true, redisStock: '98', unconfirmedReservations: 0, pendingEffects: 0, missingReceipts: false, ordersByState: [{ state: 'PAID', amount: 2 }] }
    else if (path === '/api/growth/activities') data = state.rows.filter(r => r.state === 'ACTIVE')
    else if (path === '/api/growth/orders') data = []
    else if (path === '/api/growth/wallet') { if (state.failWallet) { code = 503; message = '余额查询失败' } else data = { balance: 30 } }
    else if (path === '/api/reading/me') data = { level: 1, totalSeconds: 1800, nextLevel: 2, secondsToNext: 1800, rules: [{ level: 1, minSeconds: 0 }, { level: 2, minSeconds: 3600 }] }
    else if (path.endsWith('/run-overview')) data = { items: [] }
    else if (path.endsWith('/social/summary')) data = { messageUnread: 0, requestUnseen: 0 }
    else if (path.endsWith('/unread-count')) data = 0
    await route.fulfill({ json: { code, data, message } })
  })
  return { state, errors }
}

test('account menu opens coin shop and shop never loads administration endpoints', async ({ page }) => {
  const { state, errors } = await setup(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/growth-shop')
  await page.getByRole('button', { name: '账户菜单' }).hover()
  await expect(page.getByRole('link', { name: '硬币商城', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '管理后台', exact: true })).toBeVisible()
  await page.getByRole('link', { name: '硬币商城', exact: true }).click()
  await page.mouse.move(20, 300)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: '硬币商城', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '周末阅读成长专场' })).toBeVisible()
  expect(state.adminReads).toBe(0)
  await expect(page.getByText('活动管理', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: '../temp/coin-shop-desktop.png', fullPage: true })
  expect(errors).toEqual([])
})

test('admin creates, publishes, pauses, audits and restores an activity', async ({ page }) => {
  const { state, errors } = await setup(page); state.rows = []
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/admin?section=growth')
  await expect(page.getByRole('heading', { name: '硬币商城', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '新建活动' }).click()
  const dialog = page.getByRole('dialog', { name: '新建商城活动' })
  await dialog.getByLabel('活动名称', { exact: true }).fill('周末阅读成长专场')
  await dialog.getByLabel('活动名额（份）').fill('100')
  await dialog.getByLabel('支付期限（秒）').fill('120')
  await dialog.getByRole('button', { name: '发布活动', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(state.writes).toHaveLength(2)
  expect(state.writes[0]!.data).toMatchObject({ title: '周末阅读成长专场', stock: 100, paySeconds: 120 })
  expect(state.writes[0]!.data.startsAt).toMatch(/Z$/)
  expect(state.writes[1]!.path).toBe(`/api/growth/admin/activities/${aid}/activate`)
  await page.getByRole('button', { name: '下架活动', exact: true }).click()
  await page.getByRole('button', { name: '确认下架活动', exact: true }).click()
  await expect(page.getByText('已下架', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '查看对账', exact: true }).click()
  const audit = page.getByRole('dialog', { name: '活动库存对账' })
  await expect(audit.getByText('库存与订单记录一致')).toBeVisible()
  await audit.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('button', { name: '对账并重新上架', exact: true }).click()
  await page.getByRole('button', { name: '确认重新上架', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '重新上架', exact: true })).not.toBeVisible()
  await expect.poll(() => state.writes.at(-1)?.path).toBe(`/api/growth/admin/activities/${aid}/resume`)
  await expect(page.getByRole('button', { name: '下架活动', exact: true })).toBeVisible()
  await page.screenshot({ path: '../temp/coin-shop-admin-desktop.png', fullPage: true })
  await page.getByRole('link', { name: '查看商城' }).click()
  await expect(page.getByRole('heading', { name: '周末阅读成长专场' })).toBeVisible()
  expect(errors).toEqual([])
})

test('mobile admin validates dates, saves drafts and refreshes list', async ({ page }) => {
  const { state, errors } = await setup(page); state.rows = []
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/admin?section=growth')
  await page.getByRole('button', { name: '新建活动' }).click()
  const dialog = page.getByRole('dialog', { name: '新建商城活动' })
  await dialog.getByLabel('结束时间').fill('2020-01-01T12:00')
  await dialog.getByRole('button', { name: '保存草稿' }).click()
  await expect(dialog.getByRole('alert')).toContainText('结束时间需晚于')
  expect(state.writes).toHaveLength(0)
  await dialog.getByLabel('结束时间').fill('2099-01-01T12:00')
  await dialog.getByRole('button', { name: '保存草稿' }).click()
  await expect(dialog.getByRole('alert')).toContainText('活动最长 7 天')
  await dialog.getByLabel('结束时间').fill(new Date(Date.now() + 86400000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16))
  await page.screenshot({ path: '../temp/coin-shop-admin-mobile-dialog.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await dialog.getByRole('button', { name: '保存草稿' }).click()
  await expect(dialog).not.toBeVisible()
  expect(state.writes).toHaveLength(1)
  await expect(page.locator('.growth-admin-card .state-tag')).toHaveText('草稿')
  const previous = state.adminReads
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect.poll(() => state.adminReads).toBeGreaterThan(previous)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect(errors).toEqual([])
})

test('publish failure retains draft and retry does not create duplicate activities', async ({ page }) => {
  const { state, errors } = await setup(page); state.rows = []; state.failPublish = true
  await page.goto('/admin?section=growth')
  await page.getByRole('button', { name: '新建活动' }).click()
  await page.getByRole('dialog', { name: '新建商城活动' }).getByRole('button', { name: '发布活动', exact: true }).click()
  await expect(page.getByText(/草稿已保存，发布失败/)).toBeVisible()
  await expect(page.getByRole('dialog', { name: '新建商城活动' })).not.toBeVisible()
  await expect(page.locator('.growth-admin-card .state-tag')).toHaveText('草稿')
  state.failPublish = false
  await page.getByRole('button', { name: '发布活动', exact: true }).click()
  await page.getByRole('button', { name: '确认发布活动', exact: true }).click()
  await expect(page.getByRole('button', { name: '下架活动', exact: true })).toBeVisible()
  expect(state.writes.filter(w => w.path === '/api/growth/admin/activities')).toHaveLength(1)
  expect(errors).toEqual([])
})

test('reviewers cannot open activity administration and wallet failure leaves products usable', async ({ page }) => {
  const { state, errors } = await setup(page, 3)
  await page.goto('/admin?section=growth')
  await expect(page.getByRole('heading', { name: '概览', exact: true })).toBeVisible()
  await expect(page.locator('.admin-sidebar').getByRole('button', { name: '硬币商城' })).toHaveCount(0)
  expect(state.adminReads).toBe(0)
  state.failWallet = true
  await page.goto('/growth-shop')
  await expect(page.getByRole('alert')).toContainText('余额加载失败')
  await expect(page.getByRole('button', { name: '立即兑换' })).toBeVisible()
  await expect(page.locator('.shop-wallet strong')).toContainText('—')
  state.failWallet = false
  await page.getByRole('button', { name: '重新加载', exact: true }).click()
  await expect(page.locator('.shop-wallet strong')).toContainText('30')
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(errors).toEqual([])
})
