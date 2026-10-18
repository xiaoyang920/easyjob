import { test, expect, type Page } from '@playwright/test'

const javaCode = `import java.util.*;\n\npublic class MiniAgent {\n${Array.from({ length: 38 }, (_, i) => `    // 第 ${i + 1} 步：执行工具并收集结果\n    String step${i} = "${'a very long code line '.repeat(18)}";`).join('\n')}\n}`
const jsonCode = '{"example": "<script>window.unexpectedExecution = true</script>", "count": 2}'
const escapeHtml = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

async function fixture(page: Page) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: 'Agent 代码阅读体验', authorName: '示例作者', authorId: '7', canReadFull: true, tags: [], content: `<h2>代码示例</h2><p>可以根据阅读习惯调整文字大小，长代码也能单独放大查看。</p><pre><code class="language-java">${escapeHtml(javaCode)}</code></pre><h2>JSON 示例</h2><pre><code class="language-json">${escapeHtml(jsonCode)}</code></pre>` }
    else if (path.endsWith('/comment/list')) data = { records: [], total: 0, pages: 1 }
    else if (path.endsWith('/view')) data = { viewCount: 1 }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/article/42')
  await expect(page.locator('.article-code-toolbar')).toHaveCount(2)
  return errors
}

test('each code block expands with exact content, adjustable font, wrapping and copy; Escape restores focus', async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const errors = await fixture(page)
  const expand = page.getByRole('button', { name: '放大第 1 个代码块', exact: true })
  await expand.click()
  const originalScroll = await page.evaluate(() => scrollY)
  const dialog = page.getByRole('dialog', { name: '代码放大查看', exact: true })
  await expect(dialog).toBeVisible()
  expect(await dialog.locator('code').textContent()).toBe(javaCode)
  expect((await dialog.boundingBox())!.width).toBeGreaterThan((await page.locator('.article-content').boundingBox())!.width)
  await dialog.getByRole('button', { name: '放大代码字号', exact: true }).click()
  await expect(dialog.locator('.code-viewer-content')).toHaveCSS('font-size', '18px')
  await dialog.getByRole('button', { name: '自动换行', exact: true }).click()
  await expect(dialog.getByRole('button', { name: '自动换行', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(await dialog.locator('.code-viewer-content').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
  await dialog.getByRole('button', { name: '复制代码', exact: true }).click()
  await expect(dialog.getByRole('status')).toHaveText('已复制')
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n')).toBe(javaCode)
  await page.screenshot({ path: '../logs/article-code-viewer-desktop.png', animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(expand).toBeFocused()
  expect(await page.evaluate(() => scrollY)).toBe(originalScroll)
  await page.getByRole('button', { name: '放大第 2 个代码块', exact: true }).click()
  expect(await page.getByRole('dialog').locator('code').textContent()).toBe(jsonCode)
  expect(await page.evaluate(() => (window as any).unexpectedExecution)).toBeUndefined()
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('reading scale affects text, headings and code, stays bounded and survives refresh with width preference', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const errors = await fixture(page)
  const tools = page.getByRole('group', { name: '阅读设置', exact: true })
  const originalWidth = (await page.locator('.article-content').boundingBox())!.width
  await tools.getByRole('button', { name: '宽屏阅读', exact: true }).click()
  await expect.poll(async () => (await page.locator('.article-content').boundingBox())!.width).toBeGreaterThan(originalWidth + 200)
  const increase = tools.getByRole('button', { name: '放大正文字号', exact: true })
  for (let i = 0; i < 5; i++) await increase.click()
  await expect(increase).toBeDisabled()
  await expect(page.locator('.article-content')).toHaveCSS('font-size', '24px')
  await expect(page.locator('.article-content h2').first()).toHaveCSS('font-size', '36px')
  await expect(page.locator('.article-content pre > code').first()).toHaveCSS('font-size', '20.25px')
  // Re-rendering the controls must not remove or duplicate the DOM code tools.
  await expect(page.getByRole('button', { name: /放大第 \d+ 个代码块/ })).toHaveCount(2)
  await page.reload()
  await expect(page.locator('.article-content')).toHaveCSS('font-size', '24px')
  await expect(tools.getByRole('button', { name: '标准宽度', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await tools.getByRole('button', { name: '恢复正文默认字号', exact: true }).click()
  await expect(page.locator('.article-content')).toHaveCSS('font-size', '16px')
  await tools.getByRole('button', { name: '缩小正文字号', exact: true }).click()
  await expect(tools.getByRole('button', { name: '缩小正文字号', exact: true })).toBeDisabled()
  await tools.getByRole('button', { name: '恢复正文默认字号', exact: true }).click()
  await page.screenshot({ path: '../logs/article-reading-wide.png', animations: 'disabled' })
  expect(errors).toEqual([])
})

test('code viewer fits narrow screens and keeps controls visible while long code scrolls', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 })
  const errors = await fixture(page)
  await expect(page.getByRole('button', { name: '宽屏阅读', exact: true })).toBeHidden()
  await page.getByRole('button', { name: '放大第 1 个代码块', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '代码放大查看', exact: true })
  await expect(dialog.getByRole('button', { name: '放大代码字号', exact: true })).toBeInViewport()
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeInViewport()
  const pane = dialog.locator('.code-viewer-content')
  expect(await pane.evaluate(el => el.scrollHeight > el.clientHeight && el.scrollWidth > el.clientWidth)).toBe(true)
  await pane.evaluate(el => { el.scrollTop = el.scrollHeight; el.scrollLeft = el.scrollWidth })
  await expect(dialog.getByRole('button', { name: '自动换行', exact: true })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.screenshot({ path: '../logs/article-code-viewer-mobile.png', animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  expect(errors).toEqual([])
})
