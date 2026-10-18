import { test, expect, type Page } from '@playwright/test'

async function fixture(page: Page) {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
  })
  const requests: URL[] = []
  const question = (n: number) => ({ messageId: String(n * 2 - 1), question: `问题 ${n}`, answer: `回答 ${n}` })
  const messages = (n: number) => [
    { itemId: `message:${n * 2 - 1}`, messageId: String(n * 2 - 1), turnId: String(n * 2 - 1), role: 'user', content: `问题 ${n}` },
    { itemId: `message:${n * 2}`, messageId: String(n * 2), turnId: String(n * 2 - 1), role: 'assistant', content: `回答 ${n}\n\n${'问答测试正文。'.repeat(40)}` },
  ]
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    let data: any = []
    if (path.endsWith('/agent/library')) data = { rows: url.searchParams.get('scope')==='general' ? [{conversationId:'101',title:'分页验收'}] : [], total: 1 }
    else if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '分页验收' }]
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '分页验收' }
    else if (path.endsWith('/questions')) {
      const start = Number(url.searchParams.get('after') || 0) / 2
      const indices = Array.from({ length: 100 }, (_, i) => i + 1).filter(n => n > start).slice(0, 37)
      data = { items: indices.map(question), hasMore: indices.at(-1)! < 100, nextCursor: String(indices.at(-1)! * 2), snapshot: '199' }
    } else if (path.endsWith('/messages')) {
      requests.push(url)
      const before = url.searchParams.get('before'), after = url.searchParams.get('after'), around = url.searchParams.get('around')
      let start = 81, end = 100
      if (around) { start = Math.max(1, (Number(around) + 1) / 2 - 10); end = start + 19 }
      if (before) { end = (Number(before) + 1) / 2 - 1; start = Math.max(1, end - 19) }
      if (after) { start = (Number(after) + 1) / 2 + 1; end = Math.min(100, start + 19) }
      data = { items: Array.from({ length: end - start + 1 }, (_, i) => start + i).flatMap(messages),
        beforeCursor: String(start * 2 - 1), afterCursor: String(end * 2 - 1), hasOlder: start > 1, hasNewer: end < 100 }
    } else if (path.endsWith('/101/run')) data = null
    else if (path.includes('/agent/runs')) data = { items: [], serverTime: new Date().toISOString() }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  await expect(page.locator('.rail-tick')).toHaveCount(100)
  return requests
}

test('all question previews remain available while only a window of full turns is loaded', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  const requests = await fixture(page)
  await expect(page.locator('.message-item')).toHaveCount(40)
  expect(requests[0].searchParams.get('limit')).toBe('20')
  const old = page.getByRole('button', { name: '跳转到第 10 个提问：问题 10', exact: true })
  await old.hover()
  await expect(page.locator('.rail-preview')).toContainText('回答 10')
  await old.click()
  await expect(page.locator('[data-question-id="19"]')).toBeVisible()
  await expect(old).toHaveAttribute('aria-current', 'true')
  await expect(page.locator('.rail-tick')).toHaveCount(100)
  expect(requests.some(url => url.searchParams.get('around') === '19')).toBe(true)
  await page.getByRole('button', { name: '回到最新消息 ↓' }).click()
  await expect(page.locator('[data-question-id="199"]')).toBeVisible()
  await expect(page.locator('.message-item')).toHaveCount(40)
  expect(errors).toEqual([])
})

test('prepending older complete turns preserves the visible message position and question numbering', async ({ page }) => {
  await fixture(page)
  await page.emulateMedia({reducedMotion:'no-preference'})
  await page.locator('.message-list').evaluate(el=>Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished)))
  await page.locator('.message-list').evaluate(el => { el.scrollTop = 220 })
  const anchor = page.locator('[data-question-id="161"]')
  const before = await anchor.evaluate(el => el.getBoundingClientRect().top)
  // Trigger the same control without scrolling it into view (which would change the anchor).
  await page.getByRole('button', { name: '加载更早的消息', exact: true }).evaluate((el: HTMLButtonElement) => el.click())
  await expect(page.locator('.message-list')).toHaveAttribute('data-message-count','80')
  await expect.poll(() => page.locator('.message-item').count()).toBeLessThan(60)
  await expect(page.locator('[data-question-id="161"]')).toBeVisible()
  await expect.poll(async()=>Math.abs((await anchor.evaluate(el => el.getBoundingClientRect().top))-before)).toBeLessThan(3)
  await expect(page.locator('.rail-tick')).toHaveCount(100)
  await page.getByRole('button', { name: '跳转到第 65 个提问：问题 65', exact: true }).click()
  await expect(page.locator('[data-question-id="129"]')).toBeVisible()
})

test('history loading during generation cannot redirect streamed text into an older bubble', async ({ page }) => {
  await fixture(page)
  let release!: () => void
  let started!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const requestStarted = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/agent/chat/stream', async route => {
    started()
    await gate
    const data = ['__CONV_ID__:101', '__RUN_ID__:stream-run', '__INPUT_ID__:201',
      '__REPLY__:' + JSON.stringify({ content: '这是新问题的完整回答' }), '[DONE]']
    await route.fulfill({ contentType: 'text/event-stream', body: data.map(item => `data:${item}\n\n`).join('') })
  })
  await page.getByRole('textbox', { name: '消息内容' }).fill('新问题')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await requestStarted
  await page.getByRole('button', { name: '加载更早的消息', exact: true }).evaluate((el: HTMLButtonElement) => el.click())
  await expect(page.locator('.message-list')).toHaveAttribute('data-message-count','82')
  await expect.poll(() => page.locator('.message-item').count()).toBeLessThan(60)
  release()
  await page.getByRole('button', { name: /跳转到第 \d+ 个提问：新问题$/ }).click()
  await expect(page.locator('[data-question-id="201"]')).toContainText('新问题')
  await expect(page.locator('.message-item.assistant').last()).toContainText('这是新问题的完整回答')
  await page.getByRole('button', { name: '跳转到第 61 个提问：问题 61', exact: true }).click()
  await expect(page.locator('[data-question-id="121"]')).toContainText('问题 61')
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeVisible()
})

test('a live reply survives a distant question jump and return to the latest window', async ({ page }) => {
  await fixture(page)
  await page.evaluate(() => {
    const fetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      if (!String(input).includes('/api/agent/chat/stream')) return fetch(input, init)
      const encoder = new TextEncoder()
      const stream = new ReadableStream({ start(controller) {
        controller.enqueue(encoder.encode('data:__CONV_ID__:101\n\ndata:__RUN_ID__:live-window\n\ndata:__INPUT_ID__:201\n\n'))
        ;(window as any).finishChat = () => {
          controller.enqueue(encoder.encode('data:__REPLY__:{"content":"翻页期间生成的回答"}\n\ndata:[DONE]\n\n'))
          controller.close()
        }
      } })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
  })
  await page.route('**/api/agent/conversations/101/messages*', async route => {
    const url = new URL(route.request().url())
    if (url.searchParams.has('around') || url.searchParams.has('before') || url.searchParams.has('after')) return route.fallback()
    await route.fulfill({ json: { code: 200, data: {
      items: [{ itemId: 'message:201', messageId: '201', turnId: '201', role: 'user', content: '生成期间去看旧问题' }],
      beforeCursor: '201', afterCursor: '201', hasOlder: true, hasNewer: false,
    } } })
  })
  await page.getByRole('textbox', { name: '消息内容' }).fill('生成期间去看旧问题')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(page.locator('[data-question-id="201"]')).toBeVisible()
  await page.getByRole('button', { name: '跳转到第 10 个提问：问题 10', exact: true }).click()
  await expect(page.locator('[data-question-id="19"]')).toBeVisible()
  await expect(page.locator('[data-question-id="201"]')).toHaveCount(0)
  await page.getByRole('button', { name: '回到最新消息 ↓' }).click()
  await expect(page.locator('[data-question-id="201"]')).toHaveCount(1)
  await page.evaluate(() => (window as any).finishChat())
  await expect(page.locator('.message-item.assistant').last()).toContainText('翻页期间生成的回答')
  await expect(page.locator('.message-item')).toHaveCount(2)
})

test('a later click on a loaded question cancels an earlier slow remote jump', async ({ page }) => {
  await fixture(page)
  let release!: () => void, started!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const requestStarted = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/agent/conversations/101/messages*', async route => {
    if (!new URL(route.request().url()).searchParams.has('around')) return route.fallback()
    started(); await gate
    return route.fallback()
  })
  await page.getByRole('button', { name: '跳转到第 10 个提问：问题 10', exact: true }).click()
  await requestStarted
  const newer = page.getByRole('button', { name: '跳转到第 90 个提问：问题 90', exact: true })
  await newer.click()
  release()
  await expect(newer).toHaveAttribute('aria-current', 'true')
  await expect(page.locator('[data-question-id="179"]')).toBeVisible()
  await expect(page.locator('[data-question-id="19"]')).toHaveCount(0)
})
