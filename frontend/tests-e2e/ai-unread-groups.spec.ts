import { test, expect, type Page } from '@playwright/test'

async function setup(page: Page) {
  const now = new Date().toISOString()
  const conversations = [
    { conversationId: '101', title: '正在查看的对话' },
    { conversationId: '102', title: '后台普通聊天' },
    { conversationId: '201', title: '文章里的问题', originArticleId: '42' },
  ]
  const runs = [
    { runId: 'r101', conversationId: '101', title: '正在查看的对话', scope: 'general', status: 'succeeded', updatedAt: now, unread: false },
    { runId: 'r102', conversationId: '102', title: '后台普通聊天', scope: 'general', status: 'succeeded', updatedAt: now, unread: true },
    { runId: 'r201', conversationId: '201', title: '文章里的问题', scope: 'article', status: 'succeeded', updatedAt: now, unread: true },
    { runId: 'r299', conversationId: '299', title: '不在当前分页的文章问答', scope: 'article', status: 'succeeded', updatedAt: now, unread: true },
    { runId: 'r301', conversationId: '301', title: '草稿写作讨论', scope: 'writing', status: 'succeeded', updatedAt: now, unread: true },
  ]
  await page.addInitScript(({ runs, now }) => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('ai_run_notices:7', JSON.stringify({ items: runs, syncedAt: now }))
  }, { runs, now })
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    const cid = path.match(/\/agent\/conversations\/(\d+)/)?.[1]
    let data: any = []
    if (path.endsWith('/agent/run-overview')) data = { items: runs, serverTime: new Date().toISOString() }
    else if (path.endsWith('/agent/library')) {
      const rows = conversations.filter(conv => (conv.originArticleId ? 'article' : 'general') === url.searchParams.get('scope'))
      data = { rows, total: rows.length }
    } else if (path.endsWith('/messages')) data = [
      { messageId: `u${cid}`, role: 'user', content: '原始问题' },
      { messageId: `a${cid}`, turnId: `u${cid}`, role: 'assistant', content: '这是一条历史回答。', runId: `r${cid}`, runStatus: 'succeeded' },
    ]
    else if (path.endsWith('/questions')) data = { items: [], hasMore: false }
    else if (path.endsWith('/run')) data = null
    else if (cid) data = conversations.find(conv => conv.conversationId === cid)
    else if (path.endsWith('/agent/chat/stream')) {
      runs[0] = { ...runs[0], runId: 'live-run', status: 'running', updatedAt: new Date().toISOString(), unread: false }
      const frames = ['__CONV_ID__:101', '__RUN_ID__:live-run', '__INPUT_ID__:u-new',
        '__REPLY__:{"content":"这条回复已经在当前页面看过。"}', '__PROGRESS__:done', '[DONE]']
      return route.fulfill({ contentType: 'text/event-stream', body: frames.map(frame => `data:${frame}\n\n`).join('') })
    } else if (path.endsWith('/notification/stream')) return route.fulfill({ contentType: 'text/event-stream', body: 'event: connected\ndata: ok\n\n' })
    else if (path.endsWith('/unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  await expect(page.locator('.message-list')).toContainText('这是一条历史回答。')
  const group = (title: string) => page.locator('.conversation-group').filter({ has: page.locator('.conversation-group-title', { hasText: title }) })
  return { runs, group }
}

test('collapsed source groups show unread counts even for chats outside the loaded page', async ({ page }) => {
  const { group } = await setup(page)
  await expect(group('文章问答').locator('.conversation-group-toggle')).toHaveAttribute('aria-expanded', 'false')
  await expect(group('草稿写作').locator('.conversation-group-toggle')).toHaveAttribute('aria-expanded', 'false')
  await expect(group('普通聊天').locator('.conversation-group-toggle')).toHaveAttribute('aria-expanded', 'true')
  await expect(group('文章问答').locator('.conversation-group-updates')).toHaveText('2 条更新')
  await expect(group('草稿写作').locator('.conversation-group-updates')).toHaveText('1 条更新')
  await expect(group('普通聊天').locator('.conversation-group-updates')).toHaveText('1 条更新')
})

test('reading the live reply before the terminal poll does not create a new notice after switching chats', async ({ page }) => {
  const { runs, group } = await setup(page)
  await page.locator('textarea[placeholder]').fill('新问题')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(page.locator('.message-list')).toContainText('这条回复已经在当前页面看过。')
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('ai_run_reads:7') || '[]').some((entry: any) => entry[1].runId === 'live-run'))).toBe(true)
  await page.locator('.conversation-item').filter({ hasText: '后台普通聊天' }).locator('.conversation-open').click()
  await expect(page.locator('.conversation-item.active')).toContainText('后台普通聊天')
  runs[0] = { ...runs[0], status: 'succeeded', updatedAt: new Date(Date.now() + 1000).toISOString() }
  await page.evaluate(async () => { const monitor = await import('/src/utils/aiRuns.ts'); await monitor.refreshAiRuns() })
  await expect(group('普通聊天').locator('.conversation-group-updates')).toHaveCount(0)
  await expect(page.locator('.conversation-item').filter({ hasText: '正在查看的对话' }).locator('.conv-run-status')).toHaveCount(0)
  await expect(group('文章问答').locator('.conversation-group-updates')).toHaveText('2 条更新')
})

test('the global task panel identifies which conversation category each update belongs to', async ({ page }) => {
  await setup(page)
  await page.goto('/account-security')
  await page.locator('.ai-run-toggle').click()
  await expect(page.locator('.ai-run-menu a').filter({ hasText: '文章里的问题' }).locator('.ai-run-category')).toHaveText('文章问答')
  await expect(page.locator('.ai-run-menu a').filter({ hasText: '草稿写作讨论' }).locator('.ai-run-category')).toHaveText('草稿写作')
  await expect(page.locator('.ai-run-menu a').filter({ hasText: '后台普通聊天' }).locator('.ai-run-category')).toHaveText('普通聊天')
})
