import { expect, test } from '@playwright/test'
const spaceIconsSlot = 'spaceIcons'

function pack(id: string, name: string) {
  const images = Object.fromEntries(['article', 'collect', 'like', 'notice', 'link']
    .map(key => [key, `/uploads/icon-test/${id}/${key}.png`]))
  return { artworkId: id, slot: spaceIconsSlot, name, assets: { images, items: [] }, settings: {}, version: 1 }
}

test('a worn icon pack follows the account across pages while a visited space shows its owner’s pack', async ({ page }) => {
  const first = pack('101', '青叶图标')
  const second = pack('102', '云朵图标')
  const visitor = pack('103', '星辰图标')
  let worn: ReturnType<typeof pack> | undefined = first
  const appearance = () => ({ spaceBannerUrl: null, spaceBannerPosition: 50,
    equippedArtworks: worn ? { [spaceIconsSlot]: worn } : {} })

  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Date.now() / 1000 + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
  })
  await page.route('**/uploads/icon-test/**', async route => {
    if (route.request().url().endsWith('/102/notice.png')) return route.fulfill({ status: 404 })
    return route.fulfill({ contentType: 'image/png',
      body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABphZVxQAAAABJRU5ErkJggg==', 'base64') })
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    const article = { articleId: '42', authorId: '9', userId: '9', authorName: '示例作者', title: '图标包验收',
      canReadFull: true, tags: [], status: 1, hasLiked: true, likeCount: 1, content: '<p>测试正文</p>' }
    if (path.endsWith('/user/space/7')) data = appearance()
    else if (path.endsWith('/user/space/9')) data = { nickName: '示例作者', equippedArtworks: { [spaceIconsSlot]: visitor } }
    else if (path.endsWith('/space-customization')) data = { appearance: appearance(), products: [],
      artworks: [first, second], ownedArtworks: [first.artworkId, second.artworkId], quotes: {}, balance: 30 }
    else if (path.endsWith('/artworks/' + spaceIconsSlot)) {
      worn = route.request().method() === 'PUT' ? second : undefined
      data = appearance()
    } else if (path.endsWith('/article/recommend')) data = { records: [article], pages: 1 }
    else if (path.endsWith('/article/detail/42')) data = article
    else if (path.endsWith('/comment/list')) data = { records: [{ commentId: '77', userId: '9', userNickName: '示例作者',
      content: '测试评论', likeCount: 0, replyCount: 0 }], total: 1, current: 1, pages: 1 }
    else if (path.endsWith('unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })

  await page.goto('/')
  const navArticle = page.locator('nav a[href="/create-article"] .space-icon')
  await expect(navArticle).toHaveAttribute('src', first.assets.images.article)
  await expect(page.locator('.card-arrow .space-icon')).toHaveAttribute('src', first.assets.images.link)
  await page.goto('/article/42')
  await expect(page.getByRole('button', { name: '点赞', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.action-btn.like-btn .space-icon')).toHaveAttribute('src', first.assets.images.like)
  await expect(page.locator('.action-btn.collect-btn .space-icon')).toHaveAttribute('src', first.assets.images.collect)
  await expect(page.locator('.like-btn:not(.action-btn) .space-icon').first()).toHaveAttribute('src', first.assets.images.like)

  await page.goto('/user-space/9')
  await expect(page.locator('.tab-item .space-icon').first()).toHaveAttribute('src', visitor.assets.images.article)
  await expect(navArticle).toHaveAttribute('src', first.assets.images.article)

  await page.goto('/space-customization')
  const slot = page.locator('.customization-options section').filter({ has: page.getByRole('heading', { name: '全站图标包' }) })
  await slot.getByRole('button', { name: second.name }).click()
  await slot.getByRole('button', { name: '使用', exact: true }).click()
  await expect(navArticle).toHaveAttribute('src', second.assets.images.article)
  await expect(page.locator('nav a[href="/notifications"] svg')).toBeVisible()
  await slot.getByRole('button', { name: '取消使用' }).click()
  await expect(navArticle).toHaveCount(0)
  await expect(page.locator('nav a[href="/create-article"] svg')).toBeVisible()
})
