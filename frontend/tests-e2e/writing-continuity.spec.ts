import { test, expect, type Page } from '@playwright/test'

test.use({ actionTimeout: 8000 })
const association = 'easyjob:writing-conversation:7:'
async function fixture(page: Page, scope = '42') {
  await page.setViewportSize({ width: 1440, height: 900 })
  const sent: any[] = [], errors: string[] = [], reads: string[] = []
  const state = { failHistory: false, running: false, replayed: 0 }
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.writing`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('ai_conversation_id:7', 'unrelated-chat')
  })
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    reads.push(path)
    if (path.endsWith('/agent/chat/stream')) {
      sent.push(route.request().postDataJSON())
      return route.fulfill({ contentType: 'text/event-stream', body: ['__CONV_ID__:101', '__RUN_ID__:writing-run', '__REPLY__:{"content":"保留原意，改进表达。"}', '[DONE]'].map(data => `data:${data}\n\n`).join('') })
    }
    if (path.endsWith('/writing-run/events')) {
      state.replayed += 1
      expect(url.searchParams.get('after')).toBe('0')
      return route.fulfill({ contentType: 'text/event-stream', body: ['__REPLY__:{"content":"刷新后继续收到的回答。"}', '[DONE]'].map(data => `data:${data}\n\n`).join('') })
    }
    let data: any = []
    if (/\/article\/\d+\/edit$/.test(path)) data = { articleId: path.split('/')[3], title: '正在写的草稿', summary: '摘要', categoryId: '1', content: '<p>这是同一篇草稿的正文。</p>', status: 0, revisionId: 'qa', lockVersion: 1 }
    else if (path.endsWith('/article/create')) data = { articleId: '55', revisionId: 'qa', revisionState: 0, lockVersion: 1 }
    else if (path.endsWith('/user/space/7')) data = { userId: '7', role: 0, status: 1 }
    else if (path.endsWith('/category/list')) data = [{ categoryId: '1', categoryName: '技术' }]
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '写作对话' }
    else if (path.endsWith('/messages')) {
      if (state.failHistory) return route.fulfill({ status: 503, json: { code: 503, message: '暂时无法读取历史' } })
      data = sent.length ? [{ messageId: '1', role: 'user', content: sent[0].message }, ...(state.running ? [] : [{ messageId: '2', role: 'assistant', content: '保留原意，改进表达。' }])] : []
    } else if (path.endsWith('/run')) data = state.running ? { runId: 'writing-run', status: 'running' } : null
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto(scope === 'new' ? '/create-article' : `/create-article?id=${scope}`)
  await expect(page.locator('[data-slate-editor]')).toBeVisible()
  if (scope !== 'new') await expect(page.locator('[data-slate-editor]')).toContainText('同一篇草稿')
  const panel = page.locator('#writing-ai-panel')
  const open = async () => { await page.getByRole('button', { name: '问 AI', exact: true }).click(); await expect(panel).toBeVisible() }
  const send = async (text: string) => {
    await panel.getByRole('textbox', { name: '消息内容' }).fill(text)
    await panel.getByRole('button', { name: '发送消息', exact: true }).click()
    await expect(panel.locator('.message-bubble').last()).toContainText('改进表达')
    await expect(panel.getByRole('textbox', { name: '消息内容' })).toBeEnabled()
  }
  return { sent, reads, errors, state, panel, open, send }
}

test('reopening the same draft restores server history and continues its conversation', async ({ page }) => {
  const { sent, errors, panel, open, send } = await fixture(page)
  await open(); await send('请分析当前草稿')
  expect(await page.evaluate(key => localStorage.getItem(key), association + '42')).toBe('101')
  await page.reload(); await open()
  await expect(panel.locator('.message-bubble').first()).toContainText('请分析当前草稿')
  await expect(panel.locator('.message-bubble').last()).toContainText('改进表达')
  await send('继续润色')
  expect(sent.map(body => body.conversationId)).toEqual([null, '101'])
  expect(sent.every(body => !body.originArticleId)).toBe(true)
  expect(await page.evaluate(() => localStorage.getItem('ai_conversation_id:7'))).toBe('unrelated-chat')
  expect(errors).toEqual([])
})

test('draft and account associations do not mix, and an explicit new topic stays new after reopening', async ({ page }) => {
  const { sent, errors, reads, panel, open, send } = await fixture(page)
  await open(); await send('第一篇的讨论')
  await page.goto('/create-article?id=43'); await open()
  await expect(panel.locator('.message-bubble')).toHaveCount(0)
  await page.goto('/create-article?id=42'); await open()
  await expect(panel.locator('.message-bubble').first()).toContainText('第一篇的讨论')
  await panel.getByRole('button', { name: '新话题', exact: true }).click()
  await page.reload(); await open()
  await expect(panel.locator('.message-bubble')).toHaveCount(0)
  expect(sent).toHaveLength(1)
  await page.evaluate(() => localStorage.setItem('easyjob:writing-conversation:8:44', 'foreign-chat'))
  const before = reads.length
  await page.goto('/create-article?id=44'); await open()
  await expect(panel.locator('.message-bubble')).toHaveCount(0)
  expect(reads.slice(before).some(path => path.includes('/agent/conversations/'))).toBe(false)
  expect(errors).toEqual([])
})

test('history failure keeps the association and blocks sending until retry succeeds', async ({ page }) => {
  const { sent, errors, state, panel, open, send } = await fixture(page)
  await open(); await send('恢复失败也不要开新对话')
  state.failHistory = true
  await page.reload(); await open()
  await expect(panel.locator('.history-error')).toBeVisible()
  await expect(panel.getByRole('button', { name: '发送消息', exact: true })).toBeDisabled()
  expect(await page.evaluate(key => localStorage.getItem(key), association + '42')).toBe('101')
  expect(sent).toHaveLength(1)
  state.failHistory = false
  await panel.getByRole('button', { name: '重新加载', exact: true }).click()
  await expect(panel.locator('.history-error')).toHaveCount(0)
  await expect(panel.locator('.message-bubble').first()).toContainText('不要开新对话')
  await send('恢复后继续')
  expect(sent[1].conversationId).toBe('101')
  expect(errors).toEqual([])
})

test('first save migrates an unsaved writing conversation to the new draft ID', async ({ page }) => {
  const { sent, errors, panel, open, send } = await fixture(page, 'new')
  await page.locator('.title-input').fill('第一次保存')
  await page.locator('[data-slate-editor]').click(); await page.keyboard.insertText('草稿正文')
  await page.getByRole('combobox', { name: '文章分类' }).click()
  await page.getByRole('option', { name: '技术', exact: true }).click()
  await open(); await send('先讨论再保存')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page).toHaveURL(/create-article\?id=55$/)
  expect(await page.evaluate(key => localStorage.getItem(key), association + '55')).toBe('101')
  expect(await page.evaluate(key => localStorage.getItem(key), association + 'new')).toBeNull()
  await page.reload(); await open()
  await expect(panel.locator('.message-bubble').first()).toContainText('先讨论再保存')
  await send('保存后继续')
  expect(sent[1].conversationId).toBe('101')
  expect(errors).toEqual([])
})

test('reopened writing conversation reconnects its running response without starting a second run', async ({ page }) => {
  const { sent, errors, state, panel, open, send } = await fixture(page)
  await open(); await send('正在执行的讨论')
  state.running = true
  await page.reload(); await open()
  await expect(panel.locator('.message-bubble').last()).toContainText('刷新后继续收到的回答')
  expect(state.replayed).toBe(1)
  expect(sent).toHaveLength(1)
  expect(errors).toEqual([])
})
