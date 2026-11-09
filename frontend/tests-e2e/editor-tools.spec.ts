import { test, expect, type Page } from '@playwright/test'

test.use({ actionTimeout: 8000 })
const content = '<p>相同的文字。第一段保持不变。</p><p><strong>相同的文字。</strong>第二段待润色。<a href="https://example.org/doc">保留链接</a></p>'
async function fixture(page: Page, target: 'title' | 'summary' | 'body' | 'selection' = 'selection', delayed = false) {
  await page.setViewportSize({ width: 1440, height: 900 })
  const errors: string[] = [], sent: any[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.editor-tools`)
    localStorage.setItem('userId', '7')
  })
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/agent/chat/stream')) {
      const body = route.request().postDataJSON()
      sent.push(body)
      if (delayed) await gate
      const snapshot = body.editorContext
      const proposal = snapshot ? { id: snapshot.snapshot_id.replace(/-/g, '').repeat(2), documentId: snapshot.document_id, snapshotId: snapshot.snapshot_id,
        target, before: target === 'title' ? snapshot.title : target === 'summary' ? snapshot.summary : target === 'body' ? snapshot.content : snapshot.selection,
        after: target === 'title' ? 'AI 建议的新标题' : target === 'summary' ? '根据当前正文生成的摘要。' : target === 'body' ? '# 新的正文标题\n\n更清晰的段落。\n\n```java\nif (x < 2) run();\n```' : '已经润色的文字。',
        explanation: '保留原意，让表达更清楚。', format: target === 'body' ? 'markdown' : 'text' } : null
      const events = ['__CONV_ID__:101', '__RUN_ID__:editor-tools-run', '__REPLY__:{"content":"已准备修改建议，请确认后应用。"}',
        ...(proposal ? [`__EDITOR_EDITS__:${JSON.stringify([proposal])}`] : []), '[DONE]']
      return route.fulfill({ contentType: 'text/event-stream', body: events.map(data => `data:${data}\n\n`).join('') })
    }
    let data: any = []
    if (path.endsWith('/article/42/edit')) data = { articleId: '42', title: '原来的标题', summary: '原来的摘要', content, status: 0, revisionId: 'draft-qa', lockVersion: 1 }
    else if (path.endsWith('/user/space/7')) data = { userId: '7', role: 0, status: 1 }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/create-article?id=42')
  const editor = page.locator('[data-slate-editor]')
  await expect(editor).toContainText('第一段保持不变')
  return { editor, errors, sent, release }
}
async function selectSecondParagraph(page: Page) {
  const selected = page.locator('[data-slate-editor] p').nth(1).locator('[data-slate-string]').first()
  await selected.evaluate(el => {
    const range = document.createRange()
    range.selectNodeContents(el)
    const selection = getSelection()!
    selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  // Slate's DOM selection listener is throttled. Wait for its selected range.
  await expect(page.locator('.w-e-hover-bar')).toBeVisible()
}
async function ask(page: Page, message = '润色选中的文字') {
  await page.getByRole('button', { name: '问 AI', exact: true }).click()
  const panel = page.locator('#writing-ai-panel')
  await panel.getByRole('textbox', { name: '消息内容' }).fill(message)
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  return panel
}
async function documentMarkup(page: Page) {
  return page.locator('[data-slate-editor]').evaluate(root => {
    const clone = root.cloneNode(true) as HTMLElement
    clone.querySelectorAll('*').forEach(node => [...node.attributes].forEach(attr => {
      if (attr.name === 'id' || attr.name.startsWith('data-slate-')) node.removeAttribute(attr.name)
    }))
    return clone.innerHTML
  })
}

test('read selection and apply only the chosen occurrence after confirmation; explicit undo preserves formatting', async ({ page }, info) => {
  const { editor, errors, sent } = await fixture(page)
  const original = await documentMarkup(page)
  await selectSecondParagraph(page)
  await page.locator('.w-e-hover-bar [data-menu-key="articleAiReference"]').click()
  const panel = page.locator('#writing-ai-panel')
  await expect(panel.locator('.pending-writing-reference')).toContainText('相同的文字。')
  await panel.getByRole('textbox', { name: '消息内容' }).fill('润色引用的文字')
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await expect(review).toBeVisible()
  expect(sent[0].editorContext.selection).toBe('相同的文字。')
  expect(sent[0].editorContext.title).toBe('原来的标题')
  await expect(editor.locator('p').nth(1)).toContainText('相同的文字。')
  await review.locator('summary').click()
  await expect(review.locator('.edit-before')).toHaveText('相同的文字。')
  await page.screenshot({ path: info.outputPath('editor-change-preview.png'), animations: 'disabled' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('p').first()).toContainText('相同的文字。第一段保持不变。')
  await expect(editor.locator('p').nth(1).locator('strong')).toHaveText('已经润色的文字。')
  await expect(editor.locator('a')).toHaveAttribute('href', 'https://example.org/doc')
  await expect(review.getByRole('button', { name: '应用修改', exact: true })).toBeDisabled()
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  await expect(editor.locator('p').nth(1).locator('strong')).toHaveText('相同的文字。')
  expect(await documentMarkup(page)).toBe(original)
  expect(errors).toEqual([])
})

test('whole-body replacement renders Markdown/code safely and one editor undo restores the complete original', async ({ page }) => {
  const { editor, errors } = await fixture(page, 'body')
  const original = await documentMarkup(page)
  const panel = await ask(page, '重写整篇正文')
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('h1')).toHaveText('新的正文标题')
  await expect(editor.locator('pre')).toContainText('if (x < 2) run();')
  await editor.locator('h1').click()
  await page.keyboard.press('Control+z')
  await expect(editor.locator('p').first()).toContainText('第一段保持不变')
  expect(await documentMarkup(page)).toBe(original)
  expect(errors).toEqual([])
})

test('title proposal is a preview until confirmed and can be reverted', async ({ page }) => {
  const { errors } = await fixture(page, 'title')
  const panel = await ask(page, '帮我改标题')
  const review = panel.getByRole('region', { name: '待确认修改' })
  await expect(review).toBeVisible()
  await expect(page.locator('.title-input')).toHaveValue('原来的标题')
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(page.locator('.title-input')).toHaveValue('AI 建议的新标题')
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  await expect(page.locator('.title-input')).toHaveValue('原来的标题')
  expect(errors).toEqual([])
})

test('summary proposal applies and undoes without changing the title or body', async ({ page }) => {
  const { errors } = await fixture(page, 'summary')
  const original = await documentMarkup(page)
  const panel = await ask(page, '你帮我写个摘要')
  const review = panel.getByRole('region', { name: '待确认修改' })
  await expect(review).toContainText('摘要修改建议')
  await expect(page.locator('.summary-input')).toHaveValue('原来的摘要')
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(page.locator('.summary-input')).toBeVisible()
  await expect(page.locator('.summary-input')).toHaveValue('根据当前正文生成的摘要。')
  await expect(page.locator('.title-input')).toHaveValue('原来的标题')
  expect(await documentMarkup(page)).toBe(original)
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  await expect(page.locator('.summary-input')).toHaveValue('原来的摘要')
  expect(errors).toEqual([])
})

test('summary changes during generation or after applying are not overwritten', async ({ page }) => {
  const { sent, release } = await fixture(page, 'summary', true)
  const panel = await ask(page, '你帮我写个摘要')
  await expect.poll(() => sent.length).toBe(1)
  await page.getByRole('button', { name: '编辑摘要', exact: true }).click()
  await page.locator('.summary-input').fill('用户自己写好的摘要')
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(review.getByRole('status')).toContainText('摘要已在生成建议后发生变化')
  await expect(page.locator('.summary-input')).toHaveValue('用户自己写好的摘要')
})

test('undoing a summary proposal preserves subsequent summary edits', async ({ page }) => {
  await fixture(page, 'summary')
  const panel = await ask(page, '你帮我写个摘要')
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await page.locator('.summary-input').fill('应用后自己修改的摘要')
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  await expect(review.getByRole('status')).toContainText('摘要已继续修改')
  await expect(page.locator('.summary-input')).toHaveValue('应用后自己修改的摘要')
})

test('typing while AI works invalidates its proposal instead of overwriting new content', async ({ page }) => {
  const { editor, errors, sent, release } = await fixture(page, 'body', true)
  const panel = await ask(page, '润色正文')
  await expect.poll(() => sent.length).toBe(1)
  await editor.locator('p').first().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' 用户刚刚追加的新内容。')
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(review.getByRole('status')).toContainText('正文已在生成建议后发生变化')
  await expect(editor).toContainText('用户刚刚追加的新内容。')
  await expect(editor.locator('h1')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('title suggestions ignore body and summary edits but preserve them when applying and undoing', async ({ page }) => {
  const { editor, errors, sent, release } = await fixture(page, 'title', true)
  const panel = await ask(page, '帮我改标题')
  await expect.poll(() => sent.length).toBe(1)
  await page.getByRole('button', { name: '编辑摘要', exact: true }).click()
  await page.locator('.summary-input').fill('用户自己补充的摘要')
  await editor.locator('p').first().click()
  await page.keyboard.press('End')
  await page.keyboard.type(' 用户追加的正文。')
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(page.locator('.title-input')).toHaveValue('AI 建议的新标题')
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  await expect(page.locator('.title-input')).toHaveValue('原来的标题')
  await expect(page.locator('.summary-input')).toHaveValue('用户自己补充的摘要')
  await expect(editor).toContainText('用户追加的正文。')
  expect(errors).toEqual([])
})

test('a title changed while AI works is never overwritten', async ({ page }) => {
  const { errors, sent, release } = await fixture(page, 'title', true)
  const panel = await ask(page, '帮我改标题')
  await expect.poll(() => sent.length).toBe(1)
  await page.locator('.title-input').fill('我自己改好的标题')
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(review.getByRole('status')).toContainText('标题已在生成建议后发生变化')
  await expect(page.locator('.title-input')).toHaveValue('我自己改好的标题')
  expect(errors).toEqual([])
})

test('tracked selection follows inserted paragraphs, preserves unrelated edits and undoes only the AI replacement', async ({ page }) => {
  const { editor, errors, sent, release } = await fixture(page, 'selection', true)
  await selectSecondParagraph(page)
  const panel = await ask(page)
  await expect.poll(() => sent.length).toBe(1)
  await editor.locator('p').first().click()
  await page.keyboard.press('Control+Home')
  await page.keyboard.type('用户在前面插入的新段落。')
  await page.keyboard.press('Enter')
  await page.locator('.title-input').fill('用户新标题')
  await page.getByRole('button', { name: '编辑摘要', exact: true }).click()
  await page.locator('.summary-input').fill('用户新摘要')
  const beforeApply = await documentMarkup(page)
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('p').first()).toHaveText('用户在前面插入的新段落。')
  await expect(editor.locator('p').nth(1)).toHaveText('相同的文字。第一段保持不变。')
  await expect(editor.locator('p').nth(2).locator('strong')).toHaveText('已经润色的文字。')
  await expect(editor.locator('a')).toHaveAttribute('href', 'https://example.org/doc')
  await page.locator('.title-input').fill('应用后又改过的标题')
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  expect(await documentMarkup(page)).toBe(beforeApply)
  await expect(page.locator('.title-input')).toHaveValue('应用后又改过的标题')
  await expect(page.locator('.summary-input')).toHaveValue('用户新摘要')
  expect(errors).toEqual([])
})

test('inserting text at the selection boundary updates offsets without replacing the added text', async ({ page }) => {
  const { editor, errors, sent, release } = await fixture(page, 'selection', true)
  await selectSecondParagraph(page)
  const panel = await ask(page)
  await expect.poll(() => sent.length).toBe(1)
  const target = editor.locator('p').nth(1).locator('[data-slate-string]').first()
  await target.evaluate(el => {
    const range = document.createRange(); range.selectNodeContents(el); range.collapse(true)
    const selection = getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  await page.keyboard.type('段首新增文字：')
  await expect(editor.locator('p').nth(1)).toContainText('段首新增文字：相同的文字。')
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('p').nth(1)).toContainText('段首新增文字：已经润色的文字。')
  await expect(editor.locator('p').first()).toHaveText('相同的文字。第一段保持不变。')
  expect(errors).toEqual([])
})

test('tracked selection follows deletion and merging of the paragraph before it', async ({ page }) => {
  const { editor, errors, sent, release } = await fixture(page, 'selection', true)
  await selectSecondParagraph(page)
  const panel = await ask(page)
  await expect.poll(() => sent.length).toBe(1)
  await editor.locator('p').first().click()
  await page.keyboard.press('Control+Home')
  await expect(page.locator('.w-e-hover-bar')).toBeHidden()
  await page.keyboard.press('Shift+End')
  // Wait for wangEditor's throttled selection handler before deleting a range.
  await expect(page.locator('.w-e-hover-bar')).toBeVisible()
  await page.keyboard.press('Backspace')
  await expect(editor.locator('p').first()).toHaveText(/^[\uFEFF\u200B\s]*$/)
  await page.keyboard.press('Delete')
  await expect(editor.locator('p')).toHaveCount(1)
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('strong')).toHaveText('已经润色的文字。')
  await expect(editor).toContainText('第二段待润色。')
  await expect(editor.locator('a')).toHaveAttribute('href', 'https://example.org/doc')
  expect(errors).toEqual([])
})

test('expired snapshots cannot be applied, while the newest tracked selection remains usable', async ({ page }) => {
  const { editor, errors, sent } = await fixture(page)
  await selectSecondParagraph(page)
  const panel = await ask(page)
  const input = panel.getByRole('textbox', { name: '消息内容' })
  for (let count = 1; count < 9; count += 1) {
    await expect(input).toBeEnabled()
    await input.fill(`第 ${count + 1} 次润色选区`)
    await panel.getByRole('button', { name: '发送消息', exact: true }).click()
    await expect.poll(() => sent.length).toBe(count + 1)
  }
  const reviews = panel.getByRole('region', { name: '待确认修改' })
  await expect(reviews).toHaveCount(9)
  await reviews.first().getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(reviews.first().getByRole('status')).toContainText('编辑快照已失效')
  await reviews.last().getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('p').nth(1).locator('strong')).toHaveText('已经润色的文字。')
  await expect(editor.locator('p').first()).toHaveText('相同的文字。第一段保持不变。')
  expect(errors).toEqual([])
})

for (const change of ['text', 'format', 'delete'] as const) {
  test(`changes to the target selection are rejected (${change}), never redirected to identical text elsewhere`, async ({ page }) => {
    const { editor, errors, sent, release } = await fixture(page, 'selection', true)
    await selectSecondParagraph(page)
    const panel = await ask(page)
    await expect.poll(() => sent.length).toBe(1)
    await selectSecondParagraph(page)
    if (change === 'format') await page.keyboard.press('Control+b')
    else if (change === 'text') await page.keyboard.type('用户自己写的新文字。')
    else await page.keyboard.press('Backspace')
    const beforeApply = await documentMarkup(page)
    release()
    const review = panel.getByRole('region', { name: '待确认修改' })
    await review.getByRole('button', { name: '应用修改', exact: true }).click()
    await expect(review.getByRole('status')).toContainText(/原选区.*(变化|删除|定位)/)
    expect(await documentMarkup(page)).toBe(beforeApply)
    await expect(editor.locator('p').first()).toHaveText('相同的文字。第一段保持不变。')
    await expect(editor).not.toContainText('已经润色的文字。')
    expect(errors).toEqual([])
  })
}

test('whole-body suggestions permit title and summary edits and their undo preserves those fields', async ({ page }) => {
  const { editor, errors, sent, release } = await fixture(page, 'body', true)
  const original = await documentMarkup(page)
  const panel = await ask(page, '重写整篇正文')
  await expect.poll(() => sent.length).toBe(1)
  await page.locator('.title-input').fill('只改了标题')
  await page.getByRole('button', { name: '编辑摘要', exact: true }).click()
  await page.locator('.summary-input').fill('只改了摘要')
  release()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('h1')).toHaveText('新的正文标题')
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  expect(await documentMarkup(page)).toBe(original)
  await expect(page.locator('.title-input')).toHaveValue('只改了标题')
  await expect(page.locator('.summary-input')).toHaveValue('只改了摘要')
  expect(errors).toEqual([])
})

test('unlinked chat does not transmit the article and quoted selection stays in the composer until send', async ({ page }) => {
  const { sent, errors } = await fixture(page)
  await selectSecondParagraph(page)
  await page.getByRole('button', { name: '问 AI', exact: true }).click()
  const panel = page.locator('#writing-ai-panel')
  await panel.getByRole('button', { name: '引用内容', exact: true }).click()
  await panel.getByRole('option', { name: /选中文字/ }).click()
  await expect(panel.getByRole('textbox', { name: '消息内容' })).toHaveValue('')
  await expect(panel.locator('.pending-writing-reference')).toContainText('相同的文字。')
  expect(sent).toEqual([])
  await panel.getByRole('button', { name: '移除引用', exact: true }).click()
  await panel.getByRole('button', { name: '取消关联', exact: true }).click()
  await panel.getByRole('textbox', { name: '消息内容' }).fill('你好')
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0].editorContext).toBeUndefined()
  expect(sent[0].message).toBe('你好')
  expect(errors).toEqual([])
})

test('selection suggestions apply and undo from the mobile fullscreen panel', async ({ page }, info) => {
  const { editor, errors } = await fixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.article-rich-editor [data-menu-key="fullScreen"]').click()
  const fullscreen = page.getByRole('dialog', { name: '全屏编辑正文', exact: true })
  await expect(fullscreen).toBeVisible()
  await selectSecondParagraph(page)
  await fullscreen.getByRole('button', { name: /问 AI/ }).click()
  const panel = page.locator('#writing-ai-panel')
  await panel.getByRole('textbox', { name: '消息内容' }).fill('润色选中的文字')
  await panel.getByRole('button', { name: '发送消息', exact: true }).click()
  const review = panel.getByRole('region', { name: '待确认修改' })
  await expect(review).toBeVisible()
  await page.screenshot({ path: info.outputPath('editor-change-mobile.png'), animations: 'disabled' })
  await review.getByRole('button', { name: '应用修改', exact: true }).click()
  await expect(editor.locator('p').nth(1)).toContainText('已经润色的文字。')
  await review.getByRole('button', { name: '撤销本次修改', exact: true }).click()
  await expect(editor.locator('p').nth(1)).toContainText('相同的文字。')
  await panel.getByRole('button', { name: '收起 AI 写作助手' }).click()
  await fullscreen.getByRole('button', { name: '退出全屏' }).click()
  await expect(fullscreen).toHaveCount(0)
  expect(errors).toEqual([])
})
