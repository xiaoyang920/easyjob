import { test, expect, type Page } from '@playwright/test'

const key = 'easyjob:draft-recovery:7:42'
const content = '<h2 id="intro">Go 入门</h2><p class="legacy-paragraph">这是已经保存的正文。</p>'
const saved = { articleId: '42', title: 'Go 入门', summary: null, content, categoryId: 1,
  coverImage: null, isOriginal: 1, tags: [], status: 0, revisionId: 'r2', lockVersion: 2 }

async function fixture(page: Page, local?: { article?: Record<string, any>; content?: string }) {
  const writes: any[] = [], errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(({ key, saved, local }) => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.recovery`)
    localStorage.setItem('userId', '7')
    if (local) {
      const article = { ...saved, summary: '', categoryId: '1', coverImage: '', isOriginal: true, expectedLockVersion: 1, ...local.article }
      const html = local.content ?? saved.content
      // The signature format used by the original recovery implementation.
      const signature = JSON.stringify({ title: article.title, summary: article.summary, categoryId: article.categoryId,
        coverImage: article.coverImage, isOriginal: article.isOriginal, content: html, tags: [] })
      localStorage.setItem(key, JSON.stringify({ updatedAt: Date.now() - 2 * 86400000, article, content: html, tags: [], signature }))
    }
  }, { key, saved, local })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (route.request().method() !== 'GET') {
      if (path.startsWith('/api/article')) writes.push({ path, body: route.request().postDataJSON() })
      return route.fulfill({ json: { code: 200, data: { revisionId: 'r3', lockVersion: 3, revisionState: 0 } } })
    }
    if (path.endsWith('/article/42/edit')) data = saved
    else if (path.endsWith('/category/list')) data = [{ categoryId: '1', categoryName: '技术' }]
    else if (path.endsWith('/user/space/7')) data = { userId: '7', role: 0, status: 1 }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/edit-article?id=42')
  await expect(page.locator('[data-slate-editor]')).toContainText('这是已经保存的正文。')
  return { writes, errors }
}

test('opening a saved article does not treat editor HTML normalization as an unsaved edit', async ({ page }) => {
  const { writes, errors } = await fixture(page)
  await page.clock.install()
  await page.clock.fastForward(8000)
  await expect(page.locator('.autosave-status')).not.toContainText('有修改')
  expect(await page.evaluate(key => localStorage.getItem(key), key)).toBeNull()
  expect(writes).toEqual([])
  await page.reload()
  await expect(page.locator('[data-slate-editor]')).toContainText('这是已经保存的正文。')
  await expect(page.getByRole('button', { name: '恢复到编辑器' })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('equivalent historical snapshots with old metadata types do not ask to restore', async ({ page }) => {
  const { writes, errors } = await fixture(page, {})
  await expect(page.getByRole('button', { name: '恢复到编辑器' })).toHaveCount(0)
  expect(await page.evaluate(key => localStorage.getItem(key), key)).toBeNull()
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})

test('a genuinely different historical snapshot stays available and restores only on request', async ({ page }) => {
  const localHtml = '<p>这是本机尚未保存的新内容。</p><p><img src="/uploads/retained.png" alt="本机图片"></p>'
  const { writes, errors } = await fixture(page, { article: { title: '本机版本标题' }, content: localHtml })
  await expect(page.getByRole('button', { name: '恢复到编辑器' })).toBeVisible()
  await expect(page.locator('.title-input')).toHaveValue('Go 入门')
  expect((await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), key)).content).toBe(localHtml)
  expect(writes).toEqual([])
  await page.getByRole('button', { name: '恢复到编辑器' }).click()
  await expect(page.locator('.title-input')).toHaveValue('本机版本标题')
  await expect(page.locator('[data-slate-editor]')).toContainText('这是本机尚未保存的新内容。')
  await expect(page.locator('[data-slate-editor] img')).toHaveAttribute('src', '/uploads/retained.png')
  await expect(page.locator('.revision-notice')).toContainText('自动保存已暂停')
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})
