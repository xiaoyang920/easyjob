import { expect, test, type Page } from '@playwright/test'
import type { BannerReview, SpaceAppearance, SpaceArtwork, SpaceProduct } from '../src/utils/spaceSkins'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABphZVxQAAAABJRU5ErkJggg==', 'base64')

async function signIn(page: Page) {
  await page.addInitScript(() => {
    const payload = btoa(JSON.stringify({ sub: '7', exp: Date.now() / 1000 + 3600 }))
    localStorage.setItem('token', 'qa.' + payload + '.test')
    localStorage.setItem('userId', '7')
  })
}

test('keeps the published banner visible until the new crop is approved', async ({ page, browser, baseURL }) => {
  await signIn(page)
  const published = '/uploads/space-banners/old.webp'
  const approved = '/uploads/space-banners/new.webp'
  const reviewId = 'c96c8842-f1dc-4211-a175-a82670072142'
  const appearance: SpaceAppearance = { spaceBannerUrl: published, spaceBannerPosition: 50, equippedArtworks: {} }
  let review: BannerReview | null = null
  const profile = { userId: '7', nickName: '空间验收用户', personIntroduction: '阅读和创作', role: 1, status: 1 }
  const api = async (route: import('@playwright/test').Route) => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/user/space/7') data = { ...profile, ...appearance }
    else if (path === '/api/user/space-customization') {
      data = { appearance, balance: 50, products: [], artworks: [], ownedArtworks: [], quotes: {} }
    } else if (path === '/api/file/upload-space-banner') {
      review = { reviewId, userId: '7', nickname: profile.nickName, state: 'PENDING', position: 50, reason: null, createdAt: '2026-11-18T08:00:00' }
      data = review
    } else if (path.endsWith('/banner-review')) data = review
    else if (path.endsWith('/' + reviewId + '/image')) return route.fulfill({ contentType: 'image/webp', body: png })
    else if (path.endsWith('/' + reviewId + '/position')) {
      const input = route.request().postDataJSON()
      expect(input.view).toEqual({ ratio: '21:9', x: 0, y: 1 })
      review = { ...review!, position: input.position, view: input.view }
      data = review
    } else if (path === '/api/admin/space-banners') data = review?.state === 'PENDING' ? [review] : []
    else if (path === '/api/admin/space-banners/7/' + reviewId) {
      expect(route.request().postDataJSON().approved).toBe(true)
      review = { ...review!, state: 'APPROVED' }
      appearance.spaceBannerUrl = approved
      appearance.spaceBannerPosition = review.position
      appearance.spaceBannerView = review.view
    } else if (path === '/api/admin/me') {
      data = { userId: '7', role: 2, permissions: ['overview.read', 'reviews.read', 'reviews.manage'] }
    }
    await route.fulfill({ json: { code: 200, data } })
  }
  await page.route('**/api/**', api)
  await page.route('**/uploads/space-banners/*.webp', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.goto('/space-customization')
  await page.getByLabel('上传头图').setInputFiles({ name: 'photo.png', mimeType: 'image/png', buffer: png })
  await expect(page.getByText('新头图待审核')).toBeVisible()
  await expect(page.locator('.preview-card .space-banner img')).toHaveAttribute('src', /^blob:/)
  const position = page.getByRole('slider', { name: '头图纵向位置' })
  await position.press('Home')
  await position.press('ArrowRight')
  await page.getByLabel('头图比例').selectOption('21:9')
  await page.getByLabel('头图横向位置').press('Home')
  await page.getByRole('button', { name: '保存位置' }).click()
  await expect(page.getByText('头图位置已保存')).toBeVisible()

  const visitor = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 } })
  try {
    await visitor.route('**/api/**', api)
    await visitor.route('**/uploads/space-banners/*.webp', route => route.fulfill({ contentType: 'image/png', body: png }))
    const publicSpace = await visitor.newPage()
    await publicSpace.goto('/user-space/7')
    const banner = publicSpace.locator('.space-banner')
    await expect(banner.locator('img')).toHaveAttribute('src', published)
    await page.goto('/admin?section=spaceBanners')
    await page.getByRole('button', { name: '审核预览' }).click()
    await page.getByRole('button', { name: '通过并公开' }).click()
    await expect(page.getByText('暂无待审核头图')).toBeVisible()
    await publicSpace.reload()
    await expect(banner.locator('img')).toHaveAttribute('src', approved)
    await expect(banner.locator('img')).toHaveCSS('object-position', '0% 1%')
    await expect(banner).toHaveCSS('aspect-ratio', '21 / 9')
    await expect(publicSpace.getByRole('link', { name: '空间装扮' })).toHaveCount(0)
  } finally {
    await visitor.close()
  }
})

test('reuses the purchase request after a lost response and equips the owned artwork', async ({ page }) => {
  await signIn(page)
  const artwork: SpaceArtwork = { artworkId: 'art:000000000000000000000001', name: '青叶挂件', slot: 'avatarPendant',
    artist: '验收画师', assets: { images: { image: '/uploads/artwork/pendant.png' }, items: [] }, settings: {}, version: 1 }
  const product: SpaceProduct = { productId: 'green-pendant', name: artwork.name, coinPrice: 20, listed: true, owned: false,
    sortOrder: 1, version: 1, standaloneArtworkId: artwork.artworkId, artworks: { avatarPendant: artwork.artworkId } }
  const appearance: SpaceAppearance = { spaceBannerUrl: null, spaceBannerPosition: 50, equippedArtworks: {} }
  let balance = 50
  const attempts: string[] = []
  await page.route('**/uploads/artwork/pendant.png', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/user/space/7') data = { nickName: '空间验收用户', ...appearance }
    else if (path === '/api/reading/me' || path.endsWith('/banner-review')) data = null
    else if (path === '/api/growth/wallet') data = { balance }
    else if (path === '/api/user/space-customization') {
      data = { appearance, balance, products: [product], artworks: [artwork], ownedArtworks: product.owned ? [artwork.artworkId] : [],
        quotes: { [product.productId]: { price: 20, ownedArtworks: 0, totalArtworks: 1 } } }
    } else if (path.endsWith('/space-customization/purchase')) {
      const body = route.request().postDataJSON()
      expect(body).toMatchObject({ productId: product.productId, expectedPrice: 20 })
      attempts.push(body.requestId)
      if (!product.owned) {
        product.owned = true
        balance -= 20
        return route.abort()
      }
      data = { productId: product.productId, balance, alreadyOwned: true }
    } else if (path.endsWith('/artworks/avatarPendant')) {
      expect(route.request().postDataJSON()).toEqual({ artworkId: artwork.artworkId })
      appearance.equippedArtworks.avatarPendant = artwork
      data = appearance
    }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/growth-shop?tab=skins')
  const card = page.locator('.skin-product', { hasText: artwork.name })
  for (let attempt = 0; attempt < 2; attempt++) {
    await card.getByRole('button', { name: '购买', exact: true }).click()
    await page.getByRole('button', { name: '确定', exact: true }).click()
  }
  await card.getByRole('button', { name: '使用', exact: true }).click()
  await expect(card.getByRole('button', { name: '使用中' })).toBeDisabled()
  expect(attempts[0]).toMatch(/^[a-f0-9-]{36}$/)
  expect(attempts).toEqual([attempts[0], attempts[0]])
  expect(balance).toBe(30)
  await page.goto('/space-customization')
  await expect(page.locator('.preview-avatar .pendant-art')).toHaveAttribute('src', artwork.assets.images.image!)
})


test('display mode follows the system and keeps an explicit override across reloads', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await page.route('**/api/**', route => route.fulfill({ json: { code: 200, data: [] } }))
  await page.goto('/user-space/7')
  const html = page.locator('html')
  const control = page.locator('.theme-mode summary')
  await expect(control).toBeVisible()
  await expect(html).not.toHaveClass(/dark/)
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(html).toHaveClass(/dark/)
  await control.click()
  await page.getByRole('button', { name: '日间', exact: true }).click()
  await expect(html).not.toHaveClass(/dark/)
  await page.reload()
  await expect(html).toHaveAttribute('data-display-mode', 'light')
  await expect(html).not.toHaveClass(/dark/)
  await control.click()
  await page.getByRole('button', { name: '跟随系统' }).click()
  await expect(html).toHaveClass(/dark/)
})
