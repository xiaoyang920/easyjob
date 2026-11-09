import { test, expect, type Page } from '@playwright/test'

async function fixture(page: Page) {
  const errors: string[] = [], sent: any[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.reader`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('easyjob:writing-assistant-width', '620')
  })
  await page.routeWebSocket(/\/ws\/article/, () => {})
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: '公开文章中的 Agent', authorId: '9',
      content: '<h2>理解工具调用</h2><p>围绕发布文章阅读、解释，并查找相关资料。</p><h2>失败重试</h2><p>保留成功的结果，处理失败的任务。</p>', canReadFull: true, requiredLevel: 0, tags: [] }
    else if (path.endsWith('/agent/chat/stream')) {
      sent.push(route.request().postDataJSON())
      return route.fulfill({ contentType: 'text/event-stream', body: ['__CONV_ID__:101', `__REPLY__:${JSON.stringify({ content: '工具调用需要检查参数。'.repeat(60) })}`, '[DONE]'].map(data => `data:${data}\n\n`).join('') })
    } else if (path.endsWith('/comment/list') || path.endsWith('/comment/quote-markers')) data = { records: [], total: 0, pages: 1 }
    else if (path.startsWith('/api/reading/')) data = { sessionId: 'read-qa', sessionToken: 'read-qa', level: 0, totalSeconds: 0, nextLevel: 1, secondsToNext: 1800, rules: [] }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/article/42')
  await expect(page.locator('.article-content')).toContainText('围绕发布文章')
  const open = () => page.locator('.ask-article-ai-btn').click()
  return { errors, sent, open }
}

test('published article sidebar resizes with the reading column, remembers its own width and resets', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const { errors, sent, open } = await fixture(page)
  await open()
  const panel = page.getByRole('complementary', { name: '文章问答', exact: true })
  const handle = panel.getByRole('separator', { name: '调整文章问答宽度', exact: true })
  await expect(handle).toHaveAttribute('aria-valuenow', '480')
  await panel.getByRole('textbox', { name: '消息内容' }).fill('帮我解释这篇文章')
  const initialBody = (await page.locator('.main-content').boundingBox())!
  const grip = (await handle.boundingBox())!
  await page.mouse.move(grip.x + 6, grip.y + grip.height / 2)
  await page.mouse.down()
  await page.mouse.move(grip.x - 94, grip.y + grip.height / 2, { steps: 8 })
  await page.mouse.up()
  await expect(handle).toHaveAttribute('aria-valuenow', '580')
  const body = (await page.locator('.main-content').boundingBox())!
  expect(initialBody.width - body.width).toBeCloseTo(100, 0)
  expect(body.x + body.width).toBeLessThan((await panel.boundingBox())!.x)
  await expect(panel.getByRole('textbox', { name: '消息内容' })).toHaveValue('帮我解释这篇文章')
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(panel.locator('.message-bubble').last()).toContainText('工具调用需要检查参数')
  expect(sent[0].originArticleId).toBe('42')
  expect(sent[0].writingContext).toBeUndefined()
  expect((await panel.boundingBox())!.width).toBeCloseTo(580, 0)
  await expect.poll(() => page.evaluate(() => localStorage.getItem('easyjob:article-question-width'))).toBe('580')
  expect(await page.evaluate(() => localStorage.getItem('easyjob:writing-assistant-width'))).toBe('620')
  await page.screenshot({ path: info.outputPath('article-question-resized.png'), animations: 'disabled' })
  await panel.getByRole('button', { name: '收起文章问答' }).click()
  await open()
  await expect(handle).toHaveAttribute('aria-valuenow', '580')
  await expect(panel.locator('.message-bubble').last()).toContainText('工具调用需要检查参数')
  await page.reload(); await expect(page.locator('.article-content')).toBeVisible(); await open()
  await expect(handle).toHaveAttribute('aria-valuenow', '580')
  await handle.dblclick()
  await expect(handle).toHaveAttribute('aria-valuenow', '480')
  await handle.focus(); await page.keyboard.press('End')
  await expect(handle).toHaveAttribute('aria-valuenow', '632')
  await page.keyboard.press('Home')
  await expect(handle).toHaveAttribute('aria-valuenow', '360')
  expect(errors).toEqual([])
})

test('published article panel stays bounded on large screens and releases drag state on phones', async ({ page }) => {
  await page.setViewportSize({ width: 2555, height: 1350 })
  const { errors, open } = await fixture(page)
  await open()
  const panel = page.locator('#article-ai-panel')
  const handle = panel.getByRole('separator', { name: '调整文章问答宽度' })
  await handle.focus(); await page.keyboard.press('End')
  await expect(handle).toHaveAttribute('aria-valuenow', '800')
  expect((await panel.boundingBox())!.width).toBeLessThanOrEqual(800)
  const body = (await page.locator('.main-content').boundingBox())!
  expect(body.x + body.width).toBeLessThan((await panel.boundingBox())!.x)
  await page.getByRole('button', { name: '宽屏阅读', exact: true }).click()
  expect((await page.locator('.main-content').boundingBox())!.x + (await page.locator('.main-content').boundingBox())!.width).toBeLessThan((await panel.boundingBox())!.x)
  const grip = (await handle.boundingBox())!
  await page.mouse.move(grip.x + 6, grip.y + grip.height / 2); await page.mouse.down()
  await expect(page.locator('html')).toHaveClass(/ej-panel-resizing/)
  await page.setViewportSize({ width: 390, height: 844 }); await page.mouse.up()
  await expect(handle).toHaveCount(0)
  await expect(page.locator('html')).not.toHaveClass(/ej-panel-resizing/)
  await expect(panel.getByRole('textbox', { name: '消息内容' })).toBeInViewport()
  await expect(panel.getByRole('button', { name: '收起文章问答' })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.setViewportSize({ width: 1440, height: 900 })
  await expect(handle).toHaveAttribute('aria-valuenow', '632')
  await page.setViewportSize({ width: 2555, height: 1350 })
  await expect(handle).toHaveAttribute('aria-valuenow', '800')
  expect(errors).toEqual([])
})
