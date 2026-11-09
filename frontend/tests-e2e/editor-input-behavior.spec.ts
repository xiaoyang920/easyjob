import { test, expect, type Page, type Locator } from '@playwright/test'

async function open(page: Page, content = '<h2><strong>有格式的标题</strong></h2><p>原有正文</p><p></p>', summary = '') {
  const writes: any[] = [], errors: string[] = []
  let saved = { articleId: '42', title: '输入体验验收', summary, content, categoryId: '1', status: 0, revisionId: 'r1', lockVersion: 1 }
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('userId', '7')
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Date.now()/1000 + 3600 }))}.input`)
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/42') && route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body)
      saved = { ...saved, ...body, revisionId: 'r2', lockVersion: 2 }
      data = { revisionId: 'r2', lockVersion: 2, revisionState: 0 }
    } else if (path.endsWith('/article/42/edit')) data = saved
    else if (path.endsWith('/category/list')) data = [{ categoryId: '1', categoryName: '技术' }]
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/user/space/7')) data = { role: 0, status: 1 }
    else if (path.includes('unread-count')) data = 0
    return route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/edit-article?id=42')
  const editor = page.locator('.article-rich-editor [data-slate-editor]')
  await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
  await expect(editor).toBeVisible()
  return { editor, writes, errors }
}

async function caret(block: Locator, end = false) {
  await block.evaluate((el, end) => {
    const editor = el.closest<HTMLElement>('[data-slate-editor]')!; editor.focus()
    const leaves = el.querySelectorAll('[data-slate-string], [data-slate-zero-width]')
    const leaf = leaves[end ? leaves.length - 1 : 0]!.firstChild!
    const range = document.createRange(); range.setStart(leaf, end ? leaf.textContent!.length : 0); range.collapse(true)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  }, end)
}

for (const width of [1440, 390]) {
  test(`summary grows and shrinks with content and viewport at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 })
    await open(page, undefined, '一段简短摘要')
    await page.getByRole('button', { name: '编辑摘要', exact: true }).click()
    const summary = page.locator('.summary-input'), initial = (await summary.boundingBox())!.height
    await summary.fill(Array.from({ length: 18 }, (_, i) => `第${i}行摘要自动增高，不出现内部滚动条。`).join('\n'))
    await expect.poll(() => summary.evaluate(el => el.clientHeight >= el.scrollHeight)).toBe(true)
    expect((await summary.boundingBox())!.height).toBeGreaterThan(initial * 3)
    await page.screenshot({ path: info.outputPath(`autosize-summary-${width}.png`) })
    await page.getByRole('button', { name: '收起摘要', exact: true }).click()
    await page.getByRole('button', { name: '编辑摘要', exact: true }).click()
    await expect.poll(() => summary.evaluate(el => el.clientHeight >= el.scrollHeight)).toBe(true)
    await summary.fill('短摘要')
    await expect.poll(async () => (await summary.boundingBox())!.height).toBeLessThan(initial * 2)
    await summary.fill('摘要随可用宽度变化自动调整高度。'.repeat(25))
    await page.setViewportSize({ width: width === 1440 ? 390 : 320, height: 900 })
    await expect.poll(() => summary.evaluate(el => el.clientHeight >= el.scrollHeight)).toBe(true)
  })
}

test('Enter before a heading inserts normal prose without changing the moved heading', async ({ page }) => {
  const { editor, errors } = await open(page)
  await caret(editor.locator('h2'))
  await page.keyboard.press('Enter')
  await expect(editor.locator('h2')).toHaveText('有格式的标题')
  await expect(editor.locator('h2 strong')).toHaveText('有格式的标题')
  await expect(editor.locator(':scope > p').first()).toHaveText('')
  await page.keyboard.press('ArrowUp')
  await page.keyboard.insertText('标题前的普通文字')
  await expect(editor.locator(':scope > p').first()).toHaveText('标题前的普通文字')
  await expect(editor.locator(':scope > p').first().locator('strong')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('heading Enter clears typing format without indenting; a user Tab is preserved on save', async ({ page }) => {
  const { editor, errors, writes } = await open(page)
  await caret(editor.locator('h2'), true)
  await page.keyboard.press('Enter')
  await page.keyboard.insertText('标题后的普通正文')
  const paragraph = editor.locator('p').filter({ hasText: '标题后的普通正文' })
  await expect(paragraph).toHaveCSS('text-indent', '0px')
  await expect(paragraph.locator('strong')).toHaveCount(0)
  await page.keyboard.press('Tab')
  await expect(paragraph).toHaveCSS('text-indent', '32px')
  await page.keyboard.press('Enter'); await page.keyboard.insertText('继续写下一段')
  await expect(editor.locator('p').filter({ hasText: '继续写下一段' })).toHaveCSS('text-indent', '32px')
  await page.keyboard.press('Control+s')
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].content).toMatch(/text-indent: ?32px/)
  await page.reload()
  await expect(page.locator('[data-slate-editor] p').filter({ hasText: '标题后的普通正文' })).toHaveCSS('text-indent', '32px')
  expect(errors).toEqual([])
})

test('article title Enter focuses an empty opening paragraph without indenting it', async ({ page }) => {
  const { editor } = await open(page, '<p></p>')
  await page.locator('.title-input').press('Enter')
  await expect(editor).toBeFocused()
  await page.keyboard.insertText('首段正文')
  await expect(editor.locator('p')).toHaveCSS('text-indent', '0px')
})

test('fullscreen Tab and Shift+Tab indent prose while toolbar buttons keep keyboard navigation', async ({ page }, info) => {
  const { editor, errors } = await open(page)
  await page.locator('.toolbar [data-menu-key="fullScreen"]').click()
  await caret(editor.locator('p').filter({ hasText: '原有正文' }))
  await page.keyboard.press('Tab')
  await expect(editor).toBeFocused()
  await expect(editor.locator('p').filter({ hasText: '原有正文' })).toHaveCSS('text-indent', '32px')
  await page.keyboard.press('Shift+Tab')
  await expect(editor).toBeFocused()
  await expect(editor.locator('p').filter({ hasText: '原有正文' })).toHaveCSS('text-indent', '0px')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('p').filter({ hasText: '原有正文' })).toHaveCSS('text-indent', '32px')
  await page.screenshot({ path: info.outputPath('fullscreen-tab-indent.png') })
  const exit = page.getByRole('button', { name: /退出全屏/ })
  await exit.focus(); await page.keyboard.press('Shift+Tab')
  await expect(editor).not.toBeFocused()
  expect(errors).toEqual([])
})

test('Tab nests lists and indents code without replacing text or moving focus', async ({ page }) => {
  const { editor, errors } = await open(page, '<ul><li>第一项</li><li>第二项</li></ul><pre><code class="language-go">hello()</code></pre>')
  const items = editor.locator(':scope > div[data-slate-node="element"]')
  await caret(items.nth(1)); await page.keyboard.press('Tab')
  await expect(editor).toBeFocused()
  await expect.poll(() => items.nth(1).evaluate(el => parseFloat(getComputedStyle(el).marginLeft))).toBeGreaterThan(0)
  await page.keyboard.press('Shift+Tab')
  await expect(items.nth(1)).toHaveCSS('margin-left', '0px')
  await caret(editor.locator('pre'))
  await page.keyboard.press('Tab')
  await expect(editor.locator('pre')).toHaveText('  hello()')
  await expect(editor).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(editor.locator('pre')).toHaveText('hello()')
  expect(errors).toEqual([])
})

test('AI draft summary also grows when the dialog mounts and while typing', async ({ page }) => {
  await open(page)
  const pending = { runId: 'input-draft', draftHash: 'a'.repeat(64), title: '摘要验收', summary: '第一行\n'.repeat(15), draft: '<p>草稿正文</p>', contentFormat: 'html' }
  await page.route('**/api/agent/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/library')) data = { rows: [{ conversationId: '101', title: '摘要验收' }], total: 1 }
    else if (path.endsWith('/messages')) data = [{ role: 'assistant', content: pending.draft, isDraft: true, interrupted: true, interruptPayload: pending }]
    else if (path.endsWith('/101/run')) data = { runId: pending.runId, status: 'awaiting_approval', result: { interrupted: pending } }
    else if (path.endsWith('/run-overview')) data = { items: [] }
    return route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  await page.getByRole('button', { name: '直接编辑', exact: true }).click()
  const summary = page.getByRole('textbox', { name: '草稿摘要', exact: true })
  await summary.fill('草稿摘要自动增高\n'.repeat(18))
  await expect.poll(() => summary.evaluate(el => el.clientHeight >= el.scrollHeight)).toBe(true)
  expect((await summary.boundingBox())!.height).toBeGreaterThan(200)
})
