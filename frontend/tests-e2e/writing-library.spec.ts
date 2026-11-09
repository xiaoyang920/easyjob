import { test, expect, type Page } from '@playwright/test'

test.use({ actionTimeout: 8000 })
async function fixture(page: Page, legacy = false) {
  await page.setViewportSize({ width: 1440, height: 900 })
  const errors: string[] = [], bindings: any[] = [], sent: any[] = [], queries: URL[] = []
  const rows: any[] = [
    { conversationId: '101', title: '普通讨论', metadataVersion: 0 },
    { conversationId: '201', title: '公开文章的问题', originArticleId: '88', originArticleTitle: '公开文章' },
    { conversationId: '301', title: '润色当前草稿', isWriting: true, writingArticleId: '42', writingArticleTitle: '正在写的文章', writingArticleAvailable: true },
    { conversationId: '302', title: '未保存时的讨论', isWriting: true },
    { conversationId: '303', title: '仍保留的写作历史', isWriting: true, writingArticleId: '44', writingArticleAvailable: false }
  ]
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(legacy => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.writing-library`)
    localStorage.setItem('userId', '7')
    if (legacy) {
      localStorage.setItem('easyjob:writing-conversation:7:42', '101')
      localStorage.setItem('easyjob:writing-conversation:8:43', '999')
    }
  }, legacy)
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    let data: any = []
    if (path.endsWith('/writing-context')) {
      const id = path.split('/').at(-2)!, body = route.request().postDataJSON()
      bindings.push({ id, ...body })
      const row = rows.find(row => row.conversationId === id)!
      Object.assign(row, { isWriting: true, writingArticleId: body.articleId, writingArticleTitle: body.articleId ? '正在写的文章' : null, writingArticleAvailable: !!body.articleId })
      data = row
    } else if (path.endsWith('/agent/library')) {
      const scope = url.searchParams.get('scope')
      const selected = rows.filter(row => scope === 'writing' ? row.isWriting : scope === 'article' ? !!row.originArticleId : !row.originArticleId && !row.isWriting)
      data = { rows: selected, total: selected.length }
    } else if (/\/agent\/conversations\/\d+$/.test(path)) data = rows.find(row => row.conversationId === path.split('/').at(-1))
    else if (path.endsWith('/agent/conversations')) { queries.push(url); data = rows.filter(row => row.isWriting && row.writingArticleId === url.searchParams.get('writingArticleId')).slice(0, 1) }
    else if (path.endsWith('/messages')) data = [{ messageId: '1', role: 'user', content: '请帮我润色' }, { messageId: '2', role: 'assistant', content: '这是原来的写作讨论。' }]
    else if (path.endsWith('/run')) data = null
    else if (path.endsWith('/agent/chat/stream')) {
      const body = route.request().postDataJSON(); sent.push(body)
      const id = body.conversationId || '401'
      if (!body.conversationId) rows.push({ conversationId: id, title: '新的写作讨论', isWriting: !!body.writingContext, writingArticleId: body.writingContext?.article_id })
      return route.fulfill({ contentType: 'text/event-stream', body: [`__CONV_ID__:${id}`, '__REPLY__:{"content":"收到当前要求。"}', '[DONE]'].map(data => `data:${data}\n\n`).join('') })
    } else if (/\/article\/\d+\/edit$/.test(path)) data = { articleId: path.split('/')[3], title: '正在写的文章', content: '<p>草稿正文。</p>', categoryId: '1', status: 0, revisionId: 'qa', lockVersion: 1 }
    else if (path.endsWith('/article/create')) data = { articleId: '42', revisionId: 'qa', lockVersion: 1, revisionState: 0 }
    else if (path.endsWith('/category/list')) data = [{ categoryId: '1', categoryName: '技术' }]
    else if (path.endsWith('/user/space/7')) data = { userId: '7', role: 0, status: 1 }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/questions')) data = { items: [], hasMore: false }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  const open = async () => { await page.getByRole('button', { name: '问 AI', exact: true }).click(); await expect(page.locator('#writing-ai-panel')).toBeVisible() }
  return { rows, errors, bindings, sent, queries, open }
}

test('writing discussions form their own group with draft sources and return to the editor', async ({ page }, info) => {
  const { errors } = await fixture(page)
  await page.goto('/ai-chat?conversationId=301')
  const writing = page.locator('.conversation-group').filter({ has: page.getByRole('button', { name: '草稿写作', exact: true }) })
  const general = page.locator('.conversation-group').filter({ has: page.getByRole('button', { name: '普通聊天', exact: true }) })
  await expect(page.locator('.conversation-group-toggle > span')).toHaveText(['文章问答', '草稿写作', '普通聊天'])
  await expect(page.getByRole('button', { name: '文章问答', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await expect(writing.getByRole('button', { name: '草稿写作', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await expect(general.getByRole('button', { name: '普通聊天', exact: true })).toHaveAttribute('aria-expanded', 'true')
  await expect(writing.locator('.conversation-item')).toHaveCount(0)
  await writing.getByRole('button', { name: '草稿写作', exact: true }).click()
  await expect(writing.locator('.conversation-item')).toHaveCount(3)
  await expect(general.locator('.conversation-item')).toHaveCount(1)
  await expect(writing).toContainText('草稿：正在写的文章')
  await expect(writing).toContainText('草稿：未保存草稿')
  await expect(writing).toContainText('草稿：草稿暂不可用')
  await page.screenshot({ path: info.outputPath('writing-conversation-group.png'), animations: 'disabled' })
  await page.locator('.article-context-strip').getByRole('link').click()
  await expect(page).toHaveURL('/create-article?id=42')
  await expect(page.locator('[data-slate-editor]')).toContainText('草稿正文')
  expect(errors).toEqual([])
})

test('reopening a saved draft restores its backend association with no browser mapping', async ({ page }) => {
  const { errors, sent, queries, open } = await fixture(page)
  await page.goto('/create-article?id=42'); await open()
  await expect(page.locator('#writing-ai-panel .message-bubble').last()).toContainText('原来的写作讨论')
  expect(queries[0].searchParams.get('scope')).toBe('writing')
  expect(queries[0].searchParams.get('writingArticleId')).toBe('42')
  await page.getByRole('textbox', { name: '消息内容' }).fill('继续修改')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0].conversationId).toBe('301')
  expect(sent[0].writingContext).toEqual({ article_id: '42' })
  expect(sent[0].originArticleId).toBeUndefined()
  await expect(page.locator('#writing-ai-panel .message-bubble').last()).toContainText('收到当前要求')
  expect(errors).toEqual([])
})

test('known legacy associations move to writing without changing another account or conversation contents', async ({ page }) => {
  const { rows, errors, bindings } = await fixture(page, true)
  await page.goto('/ai-chat?conversationId=101')
  const writing = page.locator('.conversation-group').filter({ has: page.getByRole('button', { name: '草稿写作', exact: true }) })
  await writing.getByRole('button', { name: '草稿写作', exact: true }).click()
  await expect(writing.locator('.conversation-item')).toHaveCount(4)
  expect(bindings).toEqual([{ id: '101', articleId: '42' }])
  expect(rows.find(row => row.conversationId === '101').title).toBe('普通讨论')
  await expect(page.locator('.message-bubble').last()).toContainText('原来的写作讨论')
  await page.reload()
  await expect(writing.getByRole('button', { name: '草稿写作', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await writing.getByRole('button', { name: '草稿写作', exact: true }).click()
  await expect(writing.locator('.conversation-item')).toHaveCount(4)
  expect(bindings).toHaveLength(1)
  expect(errors).toEqual([])
})

test('an unsaved writing discussion binds after first save and never becomes published Q&A', async ({ page }) => {
  const { sent, errors, bindings, open } = await fixture(page)
  await page.goto('/create-article')
  await page.locator('.title-input').fill('首次保存的写作讨论')
  await page.locator('[data-slate-editor]').click(); await page.keyboard.insertText('草稿正文')
  await page.getByRole('combobox', { name: '文章分类' }).click(); await page.getByRole('option', { name: '技术', exact: true }).click()
  await open()
  await page.getByRole('textbox', { name: '消息内容' }).fill('给我建议')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect.poll(() => sent.length).toBe(1)
  await expect(page.locator('#writing-ai-panel .message-bubble').last()).toContainText('收到当前要求')
  await expect(page.getByRole('textbox', { name: '消息内容' })).toBeEnabled()
  expect(sent[0].writingContext).toEqual({ article_id: null })
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page).toHaveURL('/create-article?id=42')
  await expect.poll(() => bindings.length).toBe(1)
  expect(bindings[0]).toEqual({ id: '401', articleId: '42' })
  expect(sent[0].originArticleId).toBeUndefined()
  expect(errors).toEqual([])
})

test('a cached conversation linked to a different draft cannot be rebound or used to send', async ({ page }) => {
  const { errors, sent, bindings, open } = await fixture(page)
  await page.goto('/create-article?id=42')
  await page.evaluate(() => localStorage.setItem('easyjob:writing-conversation:7:42', '303'))
  await open()
  await expect(page.locator('#writing-ai-panel .history-error')).toBeVisible()
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeDisabled()
  expect(bindings).toEqual([]); expect(sent).toEqual([])
  expect(errors).toEqual([])
})
