import { test, expect, type Page } from '@playwright/test'

const original = '<p>开头不改变。</p><ul><li><strong>计算密集型科学计算</strong>，以及<a href="https://example.org/guide">专业说明</a>。</li><li>第二项保留。</li></ul><p>结尾不改变。</p>'
test.use({ actionTimeout: 8000 })

async function openEditor(page: Page, draftDialog = false, content = original) {
  await page.addInitScript(() => {
    const payload = btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))
    localStorage.setItem('token', `qa.${payload}.editor-test`)
    localStorage.setItem('userId', '7')
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    const pending = { runId: 'block-style-qa', draftHash: 'a'.repeat(64), title: '格式测试', draft: content, contentFormat: 'html' }
    if (path.endsWith('/article/42/edit')) data = { articleId: '42', title: '格式测试', content, status: 0, revisionId: 'qa-revision', lockVersion: 1 }
    else if (path.endsWith('/agent/library')) data = { rows: [{ conversationId: '101', title: '格式测试' }], total: 1 }
    else if (path.endsWith('/messages')) data = [{ role: 'assistant', content, isDraft: true, interrupted: true, interruptPayload: pending }]
    else if (path.endsWith('/101/run')) data = { runId: pending.runId, status: 'awaiting_approval', result: { interrupted: pending } }
    else if (path.includes('/agent/runs')) data = { items: [] }
    return route.fulfill({ json: { code: 200, data } })
  })
  await page.goto(draftDialog ? '/ai-chat?conversationId=101' : '/create-article?id=42')
  if (draftDialog) await page.getByRole('button', { name: '直接编辑', exact: true }).click()
  const editor = page.locator('.article-rich-editor [data-slate-editor]')
  await expect(editor).toContainText('开头不改变。')
  return editor
}

async function selectFirstListItem(page: Page) {
  const item = page.locator('[data-slate-editor] > div[data-slate-node="element"]').first()
  await item.evaluate(element => {
    element.closest<HTMLElement>('[data-slate-editor]')!.focus()
    const selection = window.getSelection()!
    const range = document.createRange()
    const texts = element.querySelectorAll('[data-slate-string]')
    const first = texts[0]!.firstChild!, last = texts[texts.length - 1]!.firstChild!
    range.setStart(first, 0)
    range.setEnd(last, last.textContent!.length)
    selection.removeAllRanges()
    selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  // wangEditor updates the selection toolbar asynchronously.
  const hover = page.locator('.w-e-hover-bar')
  await expect(hover).toBeVisible()
  await expect(page.locator('.article-rich-editor .toolbar [data-menu-key="bulletedList"]')).toHaveClass(/active/)
  return hover
}

for (const draftDialog of [false, true]) {
  test(`selected list text can become heading and body in ${draftDialog ? 'draft dialog' : 'article editor'}`, async ({ page }, info) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const editor = await openEditor(page, draftDialog)
    const hover = await selectFirstListItem(page)
    const format = hover.locator('.select-button').first()
    await expect(format).not.toHaveClass(/disabled/)
    await format.click()
    const heading = page.locator('.w-e-select-list:visible [data-value="header2"]').first()
    await expect(heading).toBeVisible()
    await heading.click()
    await expect(editor.locator('h2')).toContainText('计算密集型科学计算')
    await expect(editor.locator('h2 strong')).toHaveText('计算密集型科学计算')
    await expect(editor.locator('h2 a')).toHaveAttribute('href', 'https://example.org/guide')
    await expect(editor.locator(':scope > div[data-slate-node="element"]')).toHaveCount(1)
    await expect(editor.locator(':scope > div[data-slate-node="element"]')).toContainText('第二项保留。')
    await expect(editor).toContainText('开头不改变。')
    await expect(editor).toContainText('结尾不改变。')
    await editor.locator('h2').click()
    await page.locator('.article-rich-editor .toolbar .select-button').first().click()
    await page.locator('.w-e-select-list:visible [data-value="paragraph"]').first().click()
    await expect(editor.locator('h2')).toHaveCount(0)
    await expect(editor.locator('p').filter({ hasText: '计算密集型科学计算' })).toHaveCount(1)
    // "正文" is actionable even though a list initially uses that same label.
    await selectFirstListItem(page)
    await page.locator('.article-rich-editor .toolbar [data-menu-key="articleBlockStyle"]').click()
    await page.locator('.w-e-select-list:visible [data-value="paragraph"]').first().click()
    await expect(editor.locator(':scope > div[data-slate-node="element"]')).toHaveCount(0)
    await expect(editor.locator('p').filter({ hasText: '第二项保留。' })).toHaveCount(1)
    await page.keyboard.press('Control+z')
    await expect(editor.locator(':scope > div[data-slate-node="element"]')).toHaveCount(1)
    if (draftDialog) {
      await page.getByRole('button', { name: '应用修改', exact: true }).click()
      await expect(page.locator('.draft-review-body p').filter({ hasText: '计算密集型科学计算' })).toHaveCount(1)
      await expect(page.locator('.draft-review-body li')).toHaveText('第二项保留。')
    }
    await page.screenshot({ path: info.outputPath(`block-style-${draftDialog ? 'dialog' : 'article'}.png`), animations: 'disabled' })
    expect(errors).toEqual([])
  })
}

test('block format stays disabled inside code and tables', async ({ page }) => {
  const content = '<p>开头不改变。</p><pre><code class="language-java">int n = 1;</code></pre><table><tbody><tr><td>单元格保留。</td></tr></tbody></table>'
  const editor = await openEditor(page, false, content)
  const format = page.locator('.article-rich-editor .toolbar [data-menu-key="articleBlockStyle"]')
  for (const selector of ['pre code', 'td']) {
    await editor.locator(selector).click()
    await expect(format).toHaveClass(/disabled/)
    await format.click()
    await expect(page.locator('.w-e-select-list:visible')).toHaveCount(0)
  }
  await expect(editor.locator('pre')).toContainText('int n = 1;')
  await expect(editor.locator('table')).toContainText('单元格保留。')
})
