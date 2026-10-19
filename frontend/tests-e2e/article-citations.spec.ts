import { test, expect } from '@playwright/test'

const content = '<h2>学校介绍</h2><p>大学与科学院采用校院合一的管理体制<sup><a href="https://sources.example.org/intro" title="学校官网 · 学校简介">[1]</a></sup>。这段文字可以继续阅读和划线评论。</p><p>平台中的相关说明<sup><a href="/article/43" title="平台文章">[2]</a></sup>。</p>'

for (const width of [1440, 390]) {
  test(`article citations are distinct, keyboard accessible and open the original source at ${width}px`, async ({ page, context }) => {
    await page.setViewportSize({ width, height: 900 })
    await context.route('https://sources.example.org/**', route => route.fulfill({ contentType: 'text/html', body: '<h1>学校官网 · 学校简介</h1>' }))
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: unknown = []
      if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: '引用展示示例', authorName: '示例作者', authorId: '7', canReadFull: true, tags: [], content }
      else if (path.endsWith('/comment/list')) data = { records: [], total: 0, pages: 1 }
      else if (path.endsWith('/view')) data = { viewCount: 1 }
      else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
      await route.fulfill({ json: { code: 200, data } })
    })
    await page.goto('/article/42')
    const reference = page.locator('.article-content .inline-citation').first()
    await expect(reference).toHaveText('[1]')
    await expect(reference).toHaveAttribute('title', '学校官网 · 学校简介')
    const style = await reference.evaluate(element => {
      const citation = getComputedStyle(element), paragraph = getComputedStyle(element.closest('p')!)
      return { small: parseFloat(citation.fontSize) < parseFloat(paragraph.fontSize), background: citation.backgroundColor, border: citation.borderRadius, vertical: getComputedStyle(element.parentElement!).verticalAlign }
    })
    expect(style.small).toBe(true)
    expect(style.background).not.toBe('rgba(0, 0, 0, 0)')
    expect(style.border).not.toBe('0px')
    expect(style.vertical).toBe('super')
    await reference.focus()
    const popupPromise = context.waitForEvent('page')
    await reference.press('Enter')
    const popup = await popupPromise
    await expect(popup).toHaveURL('https://sources.example.org/intro')
    await popup.close()
    await expect(page.locator('.article-content a').nth(1)).toHaveAttribute('href', '/article/43')
    await page.screenshot({ path: `../temp/citation-preview-${width}.png`, fullPage: false })
  })
}
