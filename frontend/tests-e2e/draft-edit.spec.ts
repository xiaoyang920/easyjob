import { test, expect, type Page } from '@playwright/test'

// All APIs are intercepted. These checks use the actual chat page without
// creating accounts, changing real drafts or making model calls.
async function setup(page: Page, failSave = false, recoverLatest = false, formatted = false, cited = false) {
  const citations = [{ id: 'research:web1', title: '官方资料', url: 'https://sources.example.org/intro' }]
  const pending = { action: 'confirm_save_draft', runId: 'draft-qa', draftHash: 'a'.repeat(64),
    title: '缓存一致性实践', summary: '对比常见双写方案。', draft: '# 缓存一致性\n\n先更新数据库，再删除缓存。', citations: cited ? citations : [] }
  let submitted: any
  if (cited) pending.draft += '[research:web1]\n\n来源：[research:web1]'
  if (formatted) pending.draft += '\n\n```java\nint n = 1;\n```\n\n| 服务 | 作用 |\n| --- | --- |\n| Redis | 缓存 |\n\n![说明](/uploads/example.png)\n\n需要保留的段落。'
  await page.addInitScript(() => {
    const payload=btoa(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600}))
    localStorage.setItem('token', `qa.${payload}.isolated-browser-test`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('nickName', '草稿验收')
  })
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    let data: any = []
    if (url.pathname.endsWith('/chat/resume/stream')) {
      submitted = route.request().postDataJSON()
      if (failSave) return route.fulfill({ status: 409, json: { code: 409, message: '草稿版本已变化，请重新加载' } })
      return route.fulfill({ contentType: 'text/event-stream', body:
        'data:__DRAFT_SAVED__:{"draftArticleId":"900","title":"手动修改标题"}\n\n' +
        'data:__REPLY__:{"content":"草稿已保存"}\n\ndata:__PROGRESS__:done\n\ndata:[DONE]\n\n' })
    }
    if (url.pathname.endsWith('/agent/library')) data = {rows:url.searchParams.get('scope')==='general'?[{conversationId:'101',title:'缓存一致性草稿'}]:[],total:1}
    else if (url.pathname.endsWith('/agent/conversations')) data = url.searchParams.get('scope') === 'general'
      ? [{ conversationId: '101', title: '缓存一致性草稿', scope: 'general' }] : []
    else if (url.pathname.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '缓存一致性草稿', scope: 'general' }
    else if (url.pathname.endsWith('/messages')) data = [
      ...(cited ? [{ role: 'assistant', runId: 'answer-qa', content: '对话中的事实可以打开来源[research:web1]。', citations }] : []),
      { role: 'assistant', content: pending.draft, interrupted: true, isDraft: true, interruptPayload: pending }]
    else if (url.pathname.endsWith('/101/run') || url.pathname.endsWith('/runs/draft-qa')) data = submitted && failSave
      ? recoverLatest ? { runId: 'draft-qa', status: 'awaiting_approval', result: { interrupted: {
          ...pending, draftHash: 'b'.repeat(64), title: '其他窗口的新版本', draft: '# 最新版本\n不能自动覆盖。' } } }
        : { runId: 'draft-qa', status: 'failed' }
      : { runId: 'draft-qa', status: 'awaiting_approval', result: { interrupted: pending } }
    else if (url.pathname.includes('/agent/runs')) data = { items: [], serverTime: new Date().toISOString() }
    return route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  await expect(page.getByRole('button', { name: '直接编辑', exact: true })).toBeVisible()
  return () => submitted
}

async function openEditor(page: Page) {
  await page.getByRole('button', { name: '直接编辑', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '编辑草稿' })
  await expect(dialog.locator('[data-slate-editor]')).toBeVisible()
  return dialog
}

async function replaceBody(page: Page, text: string) {
  const editor = page.locator('.ai-draft-dialog [data-slate-editor]')
  await editor.fill(text)
}

test('rich edits are previewed and sent with approval on the actual chat page', async ({ page }, info) => {
  const submitted = await setup(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const dialog = await openEditor(page)
  await dialog.getByRole('textbox', { name: '草稿标题' }).fill('手动修改标题')
  await replaceBody(page, '我的修改：先更新数据库，再删除缓存。')
  expect((await dialog.locator('.editor').boundingBox())!.height).toBeGreaterThan(200)
  await page.screenshot({ path: info.outputPath('draft-edit-desktop.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: '应用修改' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.draft-review-body')).toContainText('我的修改')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.locator('.draft-link')).toBeVisible()
  expect(submitted().editedDraft.title).toBe('手动修改标题')
  expect(submitted().editedDraft.content_format).toBe('html')
  expect(submitted().editedDraft.content).toContain('我的修改')
  expect(submitted().draftHash).toBe('a'.repeat(64))
  expect(errors).toEqual([])
})

test('phone modal fits and a failed save retains manual content', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await setup(page, true)
  const dialog = await openEditor(page)
  await replaceBody(page, '不能丢失的手动修改，保存失败也要保留。')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
  const bounds = await dialog.boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.width).toBeLessThanOrEqual(390)
  await dialog.getByRole('button', { name: '应用修改' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('draft-edit-mobile.png'), fullPage: true, animations: 'disabled' })
  await dialog.getByRole('button', { name: '应用修改' }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.locator('.draft-review-body')).toContainText('不能丢失的手动修改')
  await expect(page.getByRole('button', { name: '复制保留的手动修改' })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存草稿', exact: true })).toHaveCount(0)
})

test('changed approval version keeps manual edits separate and no-op editing preserves latest Markdown', async ({ page }) => {
  const submitted = await setup(page, true, true)
  let dialog = await openEditor(page)
  await replaceBody(page, '旧版手动编辑')
  await dialog.getByRole('button', { name: '应用修改' }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByRole('button', { name: '复制保留的手动修改' })).toBeVisible()
  await expect(page.locator('.draft-review-body h1')).toHaveText('最新版本')
  dialog = await openEditor(page)
  await expect(dialog.locator('[data-slate-editor]')).toContainText('不能自动覆盖。')
  await dialog.getByRole('button', { name: '应用修改' }).click()
  await expect(page.locator('.draft-review-header h3')).toHaveText('其他窗口的新版本')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.poll(() => submitted().draftHash).toBe('b'.repeat(64))
  expect(submitted().editedDraft).toBeUndefined()
})

test('cancel discards only modal changes and unchanged editor does not replace original Markdown', async ({ page }) => {
  const submitted = await setup(page)
  let dialog = await openEditor(page)
  await dialog.getByRole('textbox', { name: '草稿标题' }).fill('不会应用的标题')
  await replaceBody(page, '不会应用的正文')
  await dialog.getByRole('button', { name: '取消修改' }).click()
  await expect(page.locator('.draft-review-header h3')).toHaveText('缓存一致性实践')
  await expect(page.locator('.draft-review-body')).not.toContainText('不会应用的正文')
  dialog = await openEditor(page)
  await dialog.getByRole('button', { name: '应用修改' }).click()
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.poll(() => submitted()?.draftHash).toBe('a'.repeat(64))
  expect(submitted().editedDraft).toBeUndefined()
})

test('formatted Markdown imports into rich editor and keeps code, table and image after editing', async ({ page }) => {
  const submitted = await setup(page, false, false, true)
  const dialog = await openEditor(page)
  await expect(dialog.locator('pre')).toContainText('int n = 1;')
  await expect(dialog.locator('table')).toContainText('Redis')
  await expect(dialog.locator('.editor img')).toHaveAttribute('src', '/uploads/example.png')
  const paragraph = dialog.locator('[data-slate-editor] p').filter({ hasText: '需要保留的段落。' })
  await paragraph.click()
  await page.keyboard.press('End')
  await page.keyboard.type('这里是手动追加的说明。')
  await dialog.getByRole('button', { name: '应用修改' }).click()
  await expect(page.locator('.draft-review-body pre')).toContainText('int n = 1;')
  await expect(page.locator('.draft-review-body table')).toContainText('Redis')
  await expect(page.locator('.draft-review-body img')).toHaveAttribute('src', '/uploads/example.png')
  await expect(page.locator('.draft-review-body')).toContainText('这里是手动追加的说明。')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.poll(() => submitted()?.editedDraft?.content_format).toBe('html')
  expect(submitted().editedDraft.content).toContain('<table')
  expect(submitted().editedDraft.content).toContain('<pre')
  expect(submitted().editedDraft.content).toContain('/uploads/example.png')
})

test('article creation uses the same editor and toolbar', async ({ page }) => {
  await setup(page)
  const dialog = await openEditor(page)
  const toolbarKeys = await dialog.locator('.toolbar button').evaluateAll(items => items.map(item => item.getAttribute('data-menu-key')))
  await dialog.getByRole('button', { name: '取消修改' }).click()
  await page.goto('/create-article')
  await expect(page.locator('.article-rich-editor [data-slate-editor]')).toBeVisible()
  expect(await page.locator('.toolbar button').evaluateAll(items => items.map(item => item.getAttribute('data-menu-key')))).toEqual(toolbarKeys)
  expect((await page.locator('.article-rich-editor .editor').boundingBox())!.height).toBeGreaterThan(400)
})

for (const width of [1440, 390]) {
  test(`chat keeps source links while draft preview and editor hide them at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 })
    const submitted = await setup(page, false, false, true, true)
    const reference = page.locator('.message-bubble .inline-citation')
    await expect(reference).toHaveText('[1]')
    await expect(reference).toHaveAttribute('href', 'https://sources.example.org/intro')
    await expect(page.locator('.draft-review-body')).not.toContainText('[research:web1]')
    await expect(page.locator('.draft-review-body')).not.toContainText('来源：')
    await expect(page.locator('.draft-review-card .inline-citation')).toHaveCount(0)
    const dialog = await openEditor(page)
    await expect(dialog.locator('[data-slate-editor]')).not.toContainText('[research:web1]')
    await expect(dialog.locator('pre')).toContainText('int n = 1;')
    await dialog.getByRole('textbox', { name: '草稿标题' }).fill('只修改标题')
    await dialog.getByRole('button', { name: '应用修改' }).click()
    await page.locator('.draft-review-card').scrollIntoViewIfNeeded()
    await page.screenshot({ path: info.outputPath(`draft-without-citations-${width}.png`), animations: 'disabled' })
    await page.getByRole('button', { name: '保存草稿', exact: true }).click()
    await expect.poll(() => submitted()?.editedDraft?.title).toBe('只修改标题')
    // Hiding a reference must not rewrite the evidence-bearing approval input.
    expect(submitted().editedDraft.content).toContain('[research:web1]')
    expect(submitted().editedDraft.content_format).not.toBe('html')
    expect(submitted().draftHash).toBe('a'.repeat(64))
  })
}
