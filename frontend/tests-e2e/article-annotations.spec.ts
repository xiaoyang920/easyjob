import { test, expect, type Page } from '@playwright/test'

const initialBody = '<h2>工具失败怎么处理</h2><p>修复仍失败，就把当前任务标记为 tool_error，由 Main 调整策略。</p><p>依赖该任务的后续任务不会执行。</p><pre><code class="language-java">String value = "hello";</code></pre><p>最后保留独立任务的成功结果。</p>'
async function fixture(page: Page, authenticated = true) {
  const errors: string[] = [], writes: any[] = [], items: any[] = [], replies: any[] = []
  let body = initialBody, failNext = false, markerBatch = 200
  page.on('pageerror', e => errors.push(e.message))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(auth => { if (auth) { localStorage.setItem('token', `eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify({ userId: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.fixture`); localStorage.setItem('userId', '7'); localStorage.setItem('nickName', '测试读者') } }, authenticated)
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    let data: any = [], code = 200, message = ''
    if (path.endsWith('/article/detail/42')) data = { articleId: '42', title: '划词评论体验', authorName: '示例作者', authorId: '9', canReadFull: true, tags: [], content: body }
    else if (path.endsWith('/comment/quote-markers')) {
      const after = BigInt(url.searchParams.get('afterId') || '0')
      const available = items.filter(c => c.quote && BigInt(c.commentId) > after).sort((a,b) => BigInt(a.commentId) > BigInt(b.commentId) ? 1 : -1)
      const selected = available.slice(0, markerBatch)
      data = { records: selected.map(c => ({ commentId: c.commentId, quote: c.quote })), nextCursor: available.length > selected.length ? selected.at(-1).commentId : '' }
    }
    else if (path.endsWith('/comment/quotes') || path.endsWith('/comment/list')) {
      const ids = url.searchParams.get('ids')?.split(',')
      const filtered = items.filter(c => (!path.endsWith('/comment/quotes') || c.quote) && (!ids || ids.includes(c.commentId)))
      const current = Number(url.searchParams.get('page') || 1), size = Number(url.searchParams.get('size') || 20)
      data = { records: filtered.slice((current-1)*size,current*size), total: filtered.length, current, pages: Math.ceil(filtered.length / size) }
    }
    else if (path.endsWith('/comment/replies')) data = { records: replies, total: replies.length, current: 1, pages: 1 }
    else if (path.endsWith('/comment/create')) {
      const payload = route.request().postDataJSON(); writes.push(payload)
      if (failNext) { code = 409; message = '文章内容已更新，请刷新后重新选择原文'; failNext = false }
      else {
        data = { commentId: String(100 + writes.length), userId: '7', userNickName: '测试读者', content: payload.content, quote: payload.quote, replyCount: 0, createTime: '2026-10-18 12:00' }
        if (payload.parentId) replies.push(data); else items.unshift(data)
      }
    } else if (route.request().method() === 'DELETE' && /\/comment\/\d+$/.test(path)) items.splice(0, 1)
    else if (path.endsWith('/view')) data = { viewCount: 1 }
    else if (path.startsWith('/api/reading/')) data = { sessionId: 'fixture', sessionToken: 'fixture', level: 0, totalSeconds: 0, nextLevel: 1, secondsToNext: 1800, rules: [{ level: 0, minSeconds: 0 }, { level: 1, minSeconds: 1800 }] }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code, data, message } })
  })
  await page.goto('/article/42')
  await expect(page.locator('.article-content')).toBeVisible()
  return { errors, writes, items, markerBatch: (size: number) => { markerBatch = size }, changeBody: (html: string) => { body = html }, fail: () => { failNext = true } }
}
async function selectText(page: Page, text: string) {
  await page.locator('.article-content').getByText(text, { exact: true }).scrollIntoViewIfNeeded()
  await page.locator('.article-content').evaluate((root, wanted) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let node: Node | null
    while ((node = walker.nextNode())) {
      const start = node.textContent!.indexOf(wanted)
      if (start < 0) continue
      const range = document.createRange(); range.setStart(node, start); range.setEnd(node, start + wanted.length)
      const selection = getSelection()!; selection.removeAllRanges(); selection.addRange(range)
      document.dispatchEvent(new Event('selectionchange')); return
    }
    throw new Error('fixture text not found')
  }, text)
  await expect(page.getByRole('button', { name: '评论所选内容', exact: false })).toBeVisible()
}

test('selection comment persists, locates original, replies and deletes through the existing endpoints', async ({ page }) => {
  await page.setViewportSize({ width: 1540, height: 960 })
  const state = await fixture(page)
  await selectText(page, '依赖该任务的后续任务不会执行。')
  await page.getByRole('button', { name: '评论所选内容', exact: false }).click()
  const panel = page.getByRole('dialog', { name: '划词评论', exact: true })
  await expect(panel).toBeVisible()
  await expect(panel.getByRole('textbox', { name: '评论内容', exact: true })).toBeFocused()
  await panel.getByRole('textbox', { name: '评论内容', exact: true }).fill('如果 B 超时，C 会被阻断吗？')
  await panel.getByRole('button', { name: '发布评论', exact: true }).click()
  await expect(panel.locator('.annotation-thread')).toHaveCount(1)
  expect(state.writes[0].quote.exact).toBe('依赖该任务的后续任务不会执行。')
  expect(state.writes[0].quote.prefix).toBeTruthy()
  await panel.getByRole('button', { name: '查看评论引用的原文' }).click()
  expect(await page.evaluate(() => (CSS as any).highlights.has('easyjob-comment'))).toBe(true)
  await page.screenshot({ path: '../logs/article-annotations-desktop.png', animations: 'disabled' })
  await panel.getByRole('button', { name: '关闭划词评论' }).click()
  await page.reload()
  await page.getByRole('button', { name: /划词评论/ }).first().click()
  await expect(panel.getByText('如果 B 超时，C 会被阻断吗？')).toBeVisible()
  await panel.getByRole('button', { name: '回复', exact: true }).click()
  await panel.getByRole('textbox', { name: '回复这条划词评论' }).fill('是的，等待 Main 调整策略。')
  await panel.getByRole('button', { name: '发布回复' }).click()
  await expect(panel.getByText('是的，等待 Main 调整策略。')).toBeVisible()
  expect(state.writes[1].parentId).toBeTruthy(); expect(state.writes[1].quote).toBeUndefined()
  await panel.getByRole('button', { name: '删除', exact: true }).click()
  await page.getByRole('dialog', { name: '删除这条评论？' }).getByRole('button', { name: '确认删除' }).click()
  await expect(panel.locator('.annotation-thread')).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('stale selection preserves typed comment and changed source does not jump to an unrelated paragraph', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await fixture(page)
  await selectText(page, '依赖该任务的后续任务不会执行。')
  await page.getByRole('button', { name: '评论所选内容', exact: false }).click()
  const panel = page.getByRole('dialog', { name: '划词评论', exact: true }), input = panel.getByRole('textbox', { name: '评论内容', exact: true })
  await input.fill('这句话的执行条件是什么？'); state.fail()
  await panel.getByRole('button', { name: '发布评论', exact: true }).click()
  await expect(panel.getByRole('alert')).toContainText('文章内容已更新')
  await expect(input).toHaveValue('这句话的执行条件是什么？')
  await panel.getByRole('button', { name: '发布评论', exact: true }).click()
  await expect(panel.locator('.annotation-thread')).toHaveCount(1)
  state.changeBody('<p>文章已改为另一个主题，原句已经删除。</p>')
  await page.reload(); await page.getByRole('button', { name: /划词评论/ }).first().click()
  await panel.getByRole('button', { name: '查看评论引用的原文' }).click()
  await expect(panel.getByRole('status')).toContainText('原文已修改或位置无法确认')
  expect(await page.evaluate(() => (CSS as any).highlights.has('easyjob-comment'))).toBe(false)
  expect(state.errors).toEqual([])
})

test('mobile selection opens a fitted drawer with visible controls, focus and Escape support', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await fixture(page)
  await selectText(page, '依赖该任务的后续任务不会执行。')
  await page.getByRole('button', { name: '评论所选内容', exact: false }).click()
  const panel = page.getByRole('dialog', { name: '划词评论', exact: true })
  await expect(panel).toHaveAttribute('aria-modal', 'true')
  await panel.getByRole('textbox', { name: '评论内容', exact: true }).fill('手机上也可以批注。')
  await expect(panel.getByRole('button', { name: '发布评论', exact: true })).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.screenshot({ path: '../logs/article-annotations-mobile.png', animations: 'disabled' })
  await page.keyboard.press('Escape'); await expect(panel).toHaveCount(0)
  await page.getByRole('button', { name: /划词评论/ }).first().click()
  await expect(panel.getByRole('textbox', { name: '评论内容', exact: true })).toHaveValue('手机上也可以批注。')
  expect(state.errors).toEqual([])
})

test('guest can browse quotes and is prompted to sign in before posting', async ({ page }) => {
  const state = await fixture(page, false)
  await selectText(page, '依赖该任务的后续任务不会执行。')
  await page.getByRole('button', { name: '评论所选内容', exact: false }).click()
  const panel = page.getByRole('dialog', { name: '划词评论', exact: true })
  await panel.getByRole('textbox', { name: '评论内容', exact: true }).fill('先写一点想法')
  await panel.getByRole('button', { name: '发布评论', exact: true }).click()
  await expect(page.locator('.el-dialog').filter({ has: page.locator('.login-form, .login-container') }).first()).toBeVisible()
  expect(state.writes).toHaveLength(0)
  expect(state.errors).toEqual([])
})

const canonical = '工具失败怎么处理 修复仍失败，就把当前任务标记为 tool_error，由 Main 调整策略。 依赖该任务的后续任务不会执行。 String value = "hello"; 最后保留独立任务的成功结果。'
function quotedComment(id: number, exact: string, content: string) {
  const start = canonical.indexOf(exact), end = start + exact.length
  return { commentId: String(id), userId: '7', userNickName: '测试读者', content, replyCount: 0, createTime: '2026-10-18 12:00', quote: { exact, start, end, prefix: canonical.slice(Math.max(0,start-48),start), suffix: canonical.slice(end,end+48) } }
}
async function clickQuotedText(page: Page, text: string) {
  const paragraph = page.locator('.article-content').getByText(text, { exact: true })
  await paragraph.scrollIntoViewIfNeeded()
  const point = await paragraph.evaluate(el => {
    const range = document.createRange(); range.selectNodeContents(el)
    const rect = range.getClientRects()[0]!
    return { x: rect.left + 10, y: rect.bottom - 1 }
  })
  await page.mouse.click(point.x, point.y)
}

test('saved comments underline their source, including older pages; clicking shows only matching threads', async ({ page }) => {
  await page.setViewportSize({ width: 1540, height: 960 })
  const state = await fixture(page)
  const target = '依赖该任务的后续任务不会执行。', other = '最后保留独立任务的成功结果。'
  state.items.push(quotedComment(101,target,'这一处的第一条讨论'), quotedComment(102,target,'这一处的第二条讨论'))
  for (let i = 0; i < 24; i++) state.items.unshift(quotedComment(200+i,other,`其他片段的讨论 ${i}`))
  state.markerBatch(7)
  await page.reload()
  const lines = page.locator('.article-comment-line')
  await expect.poll(async () => lines.count()).toBeGreaterThanOrEqual(2)
  await clickQuotedText(page, target)
  const panel = page.getByRole('dialog', { name: '划词评论', exact: true })
  await expect(panel.locator('.annotation-thread')).toHaveCount(2)
  await expect(panel.getByText('这一处的第一条讨论')).toBeVisible()
  await expect(panel.getByText('这一处的第二条讨论')).toBeVisible()
  await expect(panel.getByText('其他片段的讨论 0', { exact: true })).toHaveCount(0)
  await expect(panel.locator('.annotation-scope')).toContainText('这一处的评论 · 2')
  await page.screenshot({ path: '../logs/article-comment-underlines-desktop.png', animations: 'disabled' })
  await panel.getByRole('button', { name: '关闭划词评论' }).click()
  await expect.poll(async () => lines.count()).toBeGreaterThanOrEqual(2)
  const widthBefore = await lines.first().evaluate(el => el.getBoundingClientRect().width)
  await page.getByRole('button', { name: '放大正文字号', exact: true }).click()
  await expect.poll(async () => lines.first().evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThan(widthBefore)
  await page.getByRole('button', { name: '宽屏阅读', exact: true }).click()
  await clickQuotedText(page, target)
  await expect(panel.locator('.annotation-thread')).toHaveCount(2)
  await panel.getByRole('button', { name: '关闭划词评论' }).click()
  await clickQuotedText(page, other)
  await expect(panel.locator('.annotation-thread')).toHaveCount(20)
  await panel.getByRole('button', { name: '更多划词评论' }).click()
  await expect(panel.locator('.annotation-thread')).toHaveCount(24)
  await panel.getByRole('button', { name: '查看全部评论' }).click()
  await expect(panel.locator('.annotation-scope')).toHaveCount(0)
  await expect(panel.locator('.annotation-thread')).toHaveCount(20)
  expect(state.errors).toEqual([])
})

test('mobile taps on an underlined fragment open that location without preventing text selection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await fixture(page)
  const target = '依赖该任务的后续任务不会执行。'
  state.items.push(quotedComment(101,target,'手机点击原文的讨论'))
  await page.reload(); await expect(page.locator('.article-comment-line').first()).toBeVisible()
  await selectText(page,target)
  await expect(page.getByRole('dialog', { name: '划词评论', exact: true })).toHaveCount(0)
  await page.evaluate(() => getSelection()?.removeAllRanges())
  await clickQuotedText(page,target)
  const panel = page.getByRole('dialog', { name: '划词评论', exact: true })
  await expect(panel.getByText('手机点击原文的讨论')).toBeVisible()
  await expect(panel).toHaveAttribute('aria-modal','true')
  await page.screenshot({ path: '../logs/article-comment-underlines-mobile.png', animations: 'disabled' })
  expect(state.errors).toEqual([])
})

test('code annotations stay inside their scroll pane and disappear after deleting the last comment', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  const state = await fixture(page)
  state.changeBody('<p>前文</p><pre><code class="language-java">String value = "'+'long_code_'.repeat(50)+'";</code></pre><p>后文</p>')
  const exact = 'String value = "'+'long_code_'.repeat(50)+'";'
  const text = '前文 '+exact+' 后文', start = 3, end = 3+exact.length
  state.items.push({ ...quotedComment(101,'','代码讨论'), quote: { exact,start,end,prefix:'前文 ',suffix:' 后文' } })
  await page.reload()
  const pre = page.locator('.article-content pre'), line = page.locator('.article-comment-line').first()
  await pre.scrollIntoViewIfNeeded(); await expect(line).toBeVisible()
  const withinPane = () => page.evaluate(() => {
    const pane = document.querySelector('.article-content pre')!.getBoundingClientRect()
    return Array.from(document.querySelectorAll('.article-comment-line')).every(el => { const r=el.getBoundingClientRect(); return r.left>=pane.left-1 && r.right<=pane.right+1 && r.top>=pane.top && r.bottom<=pane.bottom+2 })
  })
  expect(await withinPane()).toBe(true)
  await pre.evaluate(el => { el.scrollLeft=el.scrollWidth })
  await expect.poll(withinPane).toBe(true)
  const point = await line.boundingBox()
  await page.mouse.click(point!.x+10,point!.y)
  const panel = page.getByRole('dialog',{name:'划词评论',exact:true})
  await expect(panel.getByText('代码讨论',{exact:true})).toBeVisible()
  await panel.getByRole('button',{name:'删除',exact:true}).click()
  await page.getByRole('dialog',{name:'删除这条评论？'}).getByRole('button',{name:'确认删除'}).click()
  await expect(page.locator('.article-comment-line')).toHaveCount(0)
  expect(state.errors).toEqual([])
})
