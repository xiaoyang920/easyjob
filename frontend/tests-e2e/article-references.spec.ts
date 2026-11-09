import { test, expect, type Page } from '@playwright/test'
import { readWritingMessage } from '../src/utils/writingReferences'
test.use({ actionTimeout: 8000 })

const first = '需要解释的第一处原文。', second = '需要对比的第二处原文。'
const body = `<h2>原文引用</h2><p>${first}</p><p>${second}</p><pre><code class="language-go">if ok {\n  run()\n}</code></pre>`
async function fixture(page: Page, options: { html?: string; anonymous?: boolean; restricted?: boolean; long?: boolean } = {}) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const sent: any[] = [], writes: string[] = [], errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(anonymous => {
    if (anonymous) return
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.article-reference`)
    localStorage.setItem('userId', '7')
  }, !!options.anonymous)
  await page.routeWebSocket(/\/ws\/article/, () => {})
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (route.request().method() !== 'GET' && (path.startsWith('/api/article/') || path.startsWith('/api/comment/'))) writes.push(path)
    if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: '发布文章引用验收', summary: '这是文章摘要', authorId: '9',
      content: options.html || (options.long ? `<p>${'长文章原文。'.repeat(2500)}</p>` : body), canReadFull: true, requiredLevel: options.restricted ? 1 : 0, tags: [] }
    else if (path.endsWith('/agent/chat/stream')) {
      sent.push(route.request().postDataJSON())
      return route.fulfill({ contentType: 'text/event-stream', body: ['__CONV_ID__:201', '__REPLY__:{"content":"可以结合引用原文来解释。"}', '[DONE]'].map(data => `data:${data}\n\n`).join('') })
    } else if (path.endsWith('/agent/conversations')) data = sent.length ? [{ conversationId: '201', title: '讨论文章', originArticleId: '42' }] : []
    else if (path.endsWith('/messages')) data = sent.length ? [{ messageId: '1', role: 'user', content: sent[0].message }, { messageId: '2', role: 'assistant', content: '可以结合引用原文来解释。' }] : []
    else if (path.endsWith('/run')) data = null
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/comment/list') || path.endsWith('/comment/quote-markers')) data = { records: [], total: 0, pages: 1 }
    else if (path.startsWith('/api/reading/')) data = { sessionId: 'read-qa', sessionToken: 'read-qa', level: 0, totalSeconds: 0, nextLevel: 1, secondsToNext: 1800, rules: [] }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/article/42')
  await expect(page.locator('.article-content')).toBeVisible()
  const open = () => page.locator('.ask-article-ai-btn').click()
  return { sent, writes, errors, open, panel: page.locator('#article-ai-panel') }
}

async function select(page: Page, text: string) {
  await page.locator('.article-content').getByText(text, { exact: true }).scrollIntoViewIfNeeded()
  await page.locator('.article-content').evaluate((root, text) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let node: Node | null
    while ((node = walker.nextNode())) {
      const at = node.textContent!.indexOf(text)
      if (at < 0) continue
      const range = document.createRange(); range.setStart(node, at); range.setEnd(node, at + text.length)
      const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
      document.dispatchEvent(new Event('selectionchange')); return
    }
    throw new Error('Fixture selection not found')
  }, text)
  await expect(page.getByRole('button', { name: '引用给 AI', exact: true })).toBeVisible()
}

const markedIds = (page: Page) => page.locator('.article-ai-reference-lines [data-reference-id]').evaluateAll(items => [...new Set(items.map(item => item.getAttribute('data-reference-id')))].length)

test('published article selections attach as multiple chips with tracked underlines, then send only after confirmation', async ({ page }, info) => {
  const { sent, writes, errors, panel } = await fixture(page)
  const original = await page.locator('.article-content').innerHTML()
  await select(page, first)
  await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(1)
  await expect.poll(() => markedIds(page)).toBe(1)
  expect(sent).toEqual([])
  await select(page, second)
  await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(2)
  await expect.poll(() => markedIds(page)).toBe(2)
  await panel.getByRole('button', { name: '移除引用 1', exact: true }).click()
  await expect.poll(() => markedIds(page)).toBe(1)
  await select(page, first); await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  await panel.getByRole('textbox', { name: '消息内容' }).fill('比较这两处内容')
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(panel.locator('.sent-writing-reference')).toHaveCount(2)
  await expect.poll(() => sent.length).toBe(1)
  expect(readWritingMessage(sent[0].message)).toEqual({ content: '比较这两处内容', references: [
    { kind: 'selection', text: second, truncated: false }, { kind: 'selection', text: first, truncated: false }
  ] })
  expect(sent[0].originArticleId).toBe('42')
  expect(sent[0].writingContext).toBeUndefined(); expect(sent[0].editorContext).toBeUndefined()
  await expect.poll(() => markedIds(page)).toBe(2)
  expect(await page.locator('.article-content').innerHTML()).toBe(original)
  expect(writes).toEqual([])
  await page.screenshot({ path: info.outputPath('published-article-references.png'), animations: 'disabled' })
  await panel.getByRole('button', { name: '新话题', exact: true }).click()
  await expect.poll(() => markedIds(page)).toBe(0)
  expect(errors).toEqual([])
})

test('@ references capture the selected text and current article, preserve code, and restore chips from history', async ({ page }) => {
  const { sent, errors, open, panel } = await fixture(page)
  await select(page, first)
  await open()
  const input = panel.getByRole('textbox', { name: '消息内容' })
  await input.fill('@选中')
  await expect(panel.getByRole('option', { name: /选中文字/ })).toBeVisible()
  await input.press('Enter')
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(1)
  await input.fill('@文章')
  await expect(panel.getByRole('option', { name: /当前文章/ })).toBeVisible()
  await input.press('Enter')
  const articleCard = panel.locator('.pending-writing-reference').filter({ hasText: '当前文章' })
  await articleCard.getByLabel('查看引用：当前文章 2').click()
  await expect(articleCard.locator('pre')).toContainText('标题：发布文章引用验收')
  await expect(articleCard.locator('pre')).toContainText('摘要：这是文章摘要')
  await expect(articleCard.locator('pre')).toContainText('if ok {\n  run()\n}')
  await expect(articleCard.locator('pre')).not.toContainText('放大查看')
  await expect(articleCard.locator('pre')).not.toContainText('复制代码')
  expect(sent).toEqual([])
  await input.fill('结合全文解释这段话')
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(panel.locator('.message-bubble').last()).toContainText('结合引用原文')
  const decoded = readWritingMessage(sent[0].message)
  expect(decoded.references?.map(item => item.kind)).toEqual(['selection', 'article'])
  await page.reload(); await expect(page.locator('.article-content')).toBeVisible(); await open()
  await expect(panel.locator('.sent-writing-reference')).toHaveCount(2)
  await expect(panel.locator('.message-bubble').first()).not.toContainText('easyjob-writing-reference')
  await expect.poll(() => markedIds(page)).toBe(0) // History text cannot identify an old DOM occurrence.
  expect(errors).toEqual([])
})

test('long selections use the AI limit independently of comment limits and reject a sixth attachment', async ({ page }) => {
  const texts = Array.from({ length: 6 }, (_, index) => `第${index + 1}处：${'原文'.repeat(600)}`)
  const { panel, sent, errors } = await fixture(page, { html: texts.map(text => `<p>${text}</p>`).join('') })
  for (const text of texts) {
    await select(page, text)
    await expect(page.getByRole('button', { name: '评论所选内容', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  }
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(5)
  await expect(panel.locator('.pending-writing-reference').first()).toContainText('第1处')
  await expect(panel.locator('.pending-writing-reference').last()).toContainText('第5处')
  await expect(page.getByText('本次最多引用 5 处，请先移除不需要的引用', { exact: true })).toBeVisible()
  await expect.poll(() => markedIds(page)).toBe(5)
  expect(sent).toEqual([]); expect(errors).toEqual([])
})

test('whole-article quotes are explicitly requested, bounded, and previewed as excerpts', async ({ page }) => {
  const { panel, sent, errors, open } = await fixture(page, { long: true })
  await open()
  await panel.getByRole('button', { name: '引用内容', exact: true }).click()
  await panel.getByRole('option', { name: /当前文章/ }).click()
  await panel.getByLabel('查看引用：当前文章').click()
  expect((await panel.locator('.reference-preview pre').innerText()).length).toBe(12000)
  await expect(panel.locator('.reference-preview')).toContainText('仅引用前 12000 字')
  expect(sent).toEqual([]); expect(errors).toEqual([])
})

test('a new oversized selection cannot silently quote a previously selected paragraph', async ({ page }) => {
  const { panel, sent, errors } = await fixture(page, { html: `${body}<p>${'字'.repeat(12001)}</p>` })
  await select(page, first); await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(1)
  await panel.getByRole('button', { name: '移除引用', exact: true }).click()
  await page.locator('.article-content > p').last().evaluate(el => {
    const range = document.createRange(); range.selectNodeContents(el)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  const input = panel.getByRole('textbox', { name: '消息内容' })
  await input.fill('@选中'); await input.press('Enter')
  await expect(page.getByText('先在正文中选中需要讨论的文字，再引用给 AI', { exact: true })).toBeVisible()
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(0)
  expect(sent).toEqual([]); expect(errors).toEqual([])
})

test('phone readers can close the drawer to add a second quote without losing the first or hiding the composer', async ({ page }, info) => {
  const { panel, sent, errors } = await fixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await select(page, first); await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(1)
  await panel.getByRole('button', { name: '收起文章问答' }).click()
  await select(page, second); await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
  await expect(panel.locator('.pending-writing-reference')).toHaveCount(2)
  await expect(panel.getByRole('textbox', { name: '消息内容' })).toBeInViewport()
  await expect(panel.getByRole('button', { name: '发送消息', exact: true })).toBeInViewport()
  await expect(panel.getByRole('button', { name: '收起文章问答' })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.screenshot({ path: info.outputPath('published-reference-phone.png'), animations: 'disabled' })
  expect(sent).toEqual([]); expect(errors).toEqual([])
})

for (const option of ['anonymous', 'restricted'] as const) {
  test(`published references preserve the ${option} access boundary`, async ({ page }) => {
    const { sent, errors } = await fixture(page, { [option]: true })
    if (option === 'restricted') {
      await expect(page.locator('.ask-article-ai-btn')).toBeDisabled()
      await page.locator('.article-content').getByText(first, { exact: true }).evaluate(el => {
        const range = document.createRange(); range.selectNodeContents(el)
        const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range); document.dispatchEvent(new Event('selectionchange'))
      })
      await expect(page.getByRole('button', { name: '评论所选内容', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '引用给 AI', exact: true })).toHaveCount(0)
    } else {
      await select(page, first); await page.getByRole('button', { name: '引用给 AI', exact: true }).click()
      await expect(page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '登录', exact: true }) })).toBeVisible()
    }
    await expect(page.locator('#article-ai-panel')).toHaveCount(0)
    expect(sent).toEqual([]); expect(errors).toEqual([])
  })
}
