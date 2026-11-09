import { test, expect } from '@playwright/test'

test('grab, refresh pending order and pay once on mobile', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(() => { localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`); localStorage.setItem('userId', '7') })
  const aid = '496effca-5f29-420e-b7ba-821ed893dc44', oid = 'a4721cbb-a61c-4d32-9c74-d43bc65fd7eb'
  let state = '', writes = 0, requestId = '', orderPolls = 0
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message))
  const order = () => ({ orderId: oid, activityId: aid, coinCost: 10, growthSeconds: 1800, state, expiresAt: new Date(Date.now() + 120000).toISOString(), reason: '' })
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname
    let data: any = null, code = 200
    if (path === '/api/growth/activities') data = [{ activityId: aid, title: '限量成长套餐', coinPrice: 10, growthSeconds: 1800, availableStock: 2, totalStock: 2, state: 'ACTIVE', startsAt: new Date(Date.now() - 60000).toISOString(), endsAt: new Date(Date.now() + 3600000).toISOString() }]
    else if (path === '/api/growth/orders') data = state ? [order()] : []
    else if (path === '/api/growth/wallet') data = { balance: state === 'PAID' ? 0 : 10 }
    else if (path === '/api/reading/me') data = { level: 0, totalSeconds: state === 'PAID' ? 1800 : 0, purchasedSeconds: state === 'PAID' ? 1800 : 0, naturalSeconds: 0, rules: [{ level: 0, minSeconds: 0 }, { level: 1, minSeconds: 3600 }], nextLevel: 1, secondsToNext: 1800 }
    else if (path.endsWith('/reservations') && req.method() === 'POST') { requestId = req.postDataJSON().requestId; data = { orderId: oid, activityId: aid, state: 'ACCEPTED' } }
    else if (path.endsWith(`/reservations/${oid}`)) { orderPolls++; data = orderPolls === 1 ? { ...order(), state: 'ACCEPTED' } : (state = 'PENDING', order()) }
    else if (path.endsWith('/pay')) { writes++; state = 'PAID'; data = order() }
    else if (path === '/api/admin/me') code = 403
    await route.fulfill({ json: { code, data, message: code === 403 ? '只有管理员可以访问' : '操作成功' } })
  })
  await page.goto('/growth-shop')
  await expect(page.getByRole('heading', { name: '硬币商城', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '立即兑换' }).click()
  await expect(page.getByText('正在确认抢购结果')).toBeVisible()
  expect(requestId).toMatch(/^[a-f0-9-]{36}$/)
  await page.reload()
  const pay = page.getByRole('button', { name: '支付 10 硬币' }); await expect(pay).toBeVisible()
  await pay.click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await expect(page.locator('.shop-order .order-state')).toHaveText('已支付，成长已到账')
  await expect(page.getByRole('dialog', { name: '确认兑换' })).not.toBeVisible()
  expect(writes).toBe(1); expect(errors).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByRole('tab', { name: '成长套餐' }).click()
  await expect(page.getByRole('button', { name: '已兑换', exact: true })).toBeDisabled()
  await page.evaluate(() => scrollTo(0, 0))
  await page.screenshot({ path: '../temp/growth-shop-mobile.png', fullPage: true })
})
