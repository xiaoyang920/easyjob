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
    else if (path === '/api/user/space-customization/orders') data = []
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

test('decoration receipts share order history with growth and appear as a purchase completes', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Date.now() / 1000 + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
  })
  const historical = { orderId: 'historical-decoration', title: '旧款头像挂件', coinCost: 15, createdAt: '2026-11-16T12:00:00Z' }
  const newOrder = { orderId: 'new-decoration', title: '森林挂件套装', coinCost: 20, createdAt: '2026-11-18T12:00:00Z' }
  const growth = { orderId: 'growth-closed', activityId: 'growth', coinCost: 10, growthSeconds: 1800,
    state: 'CLOSED', expiresAt: '2026-11-17T12:02:00Z', createdAt: '2026-11-17T12:00:00Z', reason: '超过支付期限' }
  const artworkId = 'art:000000000000000000000001', productId = 'forest-pendant'
  let purchased = false
  let finishPurchase!: () => void
  const purchaseResponse = new Promise<void>(resolve => { finishPurchase = resolve })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/growth/orders') data = [growth]
    else if (path === '/api/growth/wallet') data = { balance: 60 }
    else if (path === '/api/reading/me') data = null
    else if (path === '/api/user/space-customization/orders') data = purchased ? [newOrder, historical] : [historical]
    else if (path === '/api/user/space-customization') data = {
      appearance: { spaceBannerPosition: 50, spaceBannerUrl: null, equippedArtworks: {} },
      balance: purchased ? 40 : 60,
      products: [{ productId, name: newOrder.title, coinPrice: 25, owned: purchased, listed: true, artworks: { avatarPendant: artworkId } }],
      artworks: [{ artworkId, slot: 'avatarPendant', name: '森林挂件', assets: { images: {}, items: [] }, settings: {} }],
      ownedArtworks: purchased ? [artworkId] : [],
      quotes: { [productId]: { price: 20, ownedArtworks: 1, totalArtworks: 2 } }
    }
    else if (path === '/api/user/space-customization/purchase') {
      expect(route.request().postDataJSON()).toMatchObject({ productId, expectedPrice: 20 })
      await purchaseResponse
      purchased = true
      data = { productId, balance: 40, alreadyOwned: false }
    }
    await route.fulfill({ json: { code: 200, data } })
  })

  await page.goto('/growth-shop')
  await page.getByRole('tab', { name: '空间装扮' }).click()
  await page.getByRole('button', { name: '购买', exact: true }).click()
  const submitted = page.waitForRequest('**/api/user/space-customization/purchase')
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await submitted
  await page.getByRole('tab', { name: '我的订单' }).click()
  const titles = page.locator('.shop-order h3')
  await expect(titles).toHaveText(['30 分钟阅读成长', historical.title])
  finishPurchase()
  await expect(titles).toHaveText([newOrder.title, '30 分钟阅读成长', historical.title])
  const receipt = page.locator('.shop-order').first()
  await expect(receipt).toContainText('已支付')
  await expect(receipt).toContainText('20 硬币')
  await expect(receipt).toContainText('订单号 ' + newOrder.orderId)
  await expect(receipt.getByRole('button')).toHaveCount(0)
  await page.reload()
  await page.getByRole('tab', { name: '我的订单' }).click()
  await expect(titles).toHaveText([newOrder.title, '30 分钟阅读成长', historical.title])
})
