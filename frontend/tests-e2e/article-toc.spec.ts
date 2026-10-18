import { test, expect, type Page } from '@playwright/test'

const longTitle = 'Agent 开发入门：从一次问答到动手的智能体，理解规划、工具调用、长期记忆与执行循环的完整过程'
const headings = [longTitle, ...Array.from({ length: 35 }, (_, i) => `${i + 1}. ${i % 2 ? '工具调用与运行结果的处理流程' : 'EmbeddingBatchExecutorConfigurationAndConcurrentExecution'} 的详细说明`)]

async function articleFixture(page: Page) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const content = headings.map((text, i) => {
    const level = i % 6 + 1
    return `<h${level}>${text}</h${level}><p>${'这是用于目录布局验收的正文。'.repeat(30)}</p>`
  }).join('')
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: '长文章目录验收', content, authorId: '7', authorName: '示例作者', tags: [], canReadFull: true }
    else if (path.endsWith('/comment/list')) data = { records: [], total: 0, pages: 1 }
    else if (path.endsWith('/view')) data = { viewCount: 1 }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/article/42')
  await expect(page.locator('.toc-item')).toHaveCount(headings.length)
  return errors
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 600 }]) {
  test(`long headings wrap completely and the outline scrolls independently at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const errors = await articleFixture(page)
    const outline = page.getByRole('navigation', { name: '文章目录', exact: true })
    const first = outline.getByRole('link', { name: longTitle, exact: true })
    const layout = await first.evaluate(el => {
      const rect = el.getBoundingClientRect(), range = document.createRange()
      range.selectNodeContents(el)
      return { height: rect.height, lineHeight: parseFloat(getComputedStyle(el).lineHeight), complete: Array.from(range.getClientRects()).every(line => line.bottom <= rect.bottom + 1 && line.right <= rect.right + 1) }
    })
    expect(layout.height).toBeGreaterThan(layout.lineHeight * 2)
    expect(layout.complete).toBe(true)
    // Also cover long unbroken technical names and all six heading levels.
    expect(await outline.locator('a').evaluateAll(links => links.every(el => el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight + 1))).toBe(true)
    const titleBefore = (await page.locator('.toc-title').boundingBox())!
    const pageScroll = await page.evaluate(() => scrollY)
    await outline.hover()
    await page.mouse.wheel(0, 20000)
    await expect(outline.getByRole('link').last()).toBeInViewport()
    expect(await page.evaluate(() => scrollY)).toBe(pageScroll)
    expect((await page.locator('.toc-title').boundingBox())!.y).toBe(titleBefore.y)
    expect((await outline.boundingBox())!.y + (await outline.boundingBox())!.height).toBeLessThanOrEqual(viewport.height - 16)
    await page.screenshot({ path: `../logs/article-toc-${viewport.width}.png`, animations: 'disabled' })
    expect(errors).toEqual([])
  })
}

test('outline links land below the shared navigation and the active heading stays reachable', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 700 })
  const errors = await articleFixture(page)
  const outline = page.getByRole('navigation', { name: '文章目录', exact: true })
  const target = outline.getByRole('link', { name: headings[18], exact: true })
  await target.click()
  await expect(target).toHaveAttribute('aria-current', 'location')
  const headingOffset = (await page.locator('.app-header').boundingBox())!.height + (await page.locator('.article-reading-tools').boundingBox())!.height + 8 + 16
  await expect.poll(async () => Math.round((await page.locator('.article-content :is(h1,h2,h3,h4,h5,h6)').nth(18).boundingBox())!.y)).toBe(headingOffset)
  // Reading another section should scroll the outline itself to reveal its active link.
  await page.mouse.move(800, 500)
  await page.waitForTimeout(180)
  await page.evaluate(offset => {
    const heading = document.querySelectorAll('.article-content :is(h1,h2,h3,h4,h5,h6)')[28]!
    window.scrollTo({ top: heading.getBoundingClientRect().top + scrollY - offset, behavior: 'instant' })
  }, headingOffset)
  const active = outline.getByRole('link', { name: headings[28], exact: true })
  await expect(active).toHaveAttribute('aria-current', 'location')
  await expect(active).toBeInViewport()
  await expect(page.locator('.toc-title')).toBeInViewport()
  await outline.focus()
  await expect(outline).toBeFocused()
  await page.screenshot({ path: '../logs/article-toc-active.png', animations: 'disabled' })
  expect(errors).toEqual([])
})
