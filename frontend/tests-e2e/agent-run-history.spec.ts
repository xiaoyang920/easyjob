import { test, expect } from '@playwright/test'

for (const race of [false, true]) {
  test(`successful replies preserve activities and elapsed time after refresh${race ? ' during settlement' : ''}`, async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
      localStorage.setItem('userId', '7')
    })
    let historyReads = 0
    let statusReads = 0
    const executions: string[] = []
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const question = { messageId: '1', role: 'user', content: '说明刷新后的活动记录' }
    const answer = { messageId: '2', role: 'assistant', runId: 'successful-run', runStatus: 'succeeded',
      content: '回答内容保留。', runStartedAt: '2026-10-11T01:00:00Z', runFinishedAt: '2026-10-11T01:00:22Z',
      agentEvents: [
        { version: 1, kind: 'commentary', text: '我会直接回答这个问题。' },
        { version: 1, kind: 'activity', id: 'main', label: '理解请求', status: 'active', timestamp: '2026-10-11T01:00:01Z' },
        { version: 1, kind: 'activity', id: 'main', label: '理解请求', status: 'done', timestamp: '2026-10-11T01:00:21Z' },
        { version: 1, kind: 'activity', id: 'main/grounding', label: '依据核验完成', status: 'done', timestamp: '2026-10-11T01:00:22Z' },
        { version: 1, kind: 'status', status: 'complete' },
      ] }
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: any = []
      if (/\/chat\/stream$|\/recover$|\/events$/.test(path)) executions.push(path)
      if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '活动恢复验收', scope: 'general' }]
      else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '活动恢复验收', scope: 'general' }
      else if (path.endsWith('/messages')) {
        historyReads++
        data = { items: [question, ...(race && historyReads === 1 ? [] : [answer])], hasOlder: false, hasNewer: false }
      } else if (path.endsWith('/101/run')) {
        statusReads++
        data = { runId: 'successful-run', status: 'succeeded', result: { reply: answer.content } }
      }
      await route.fulfill({ json: { code: 200, data } })
    })
    await page.goto('/ai-chat?conversationId=101')
    const reply = page.locator('.message-item.assistant').first()
    for (let attempt = 0; attempt < 2; attempt++) {
      await expect.poll(() => statusReads).toBe(attempt + 1)
      await expect(reply.locator('.activity-summary')).toHaveText('处理完成 · 2 项活动')
      await expect(reply.locator('.activity-duration')).toHaveText('22 秒')
      await reply.locator('.activity-header').click()
      await expect(reply.locator('.activity-header')).toHaveAttribute('aria-expanded', 'true')
      await expect(reply.locator('.activity-item')).toHaveCount(2)
      await expect(reply.locator('.item-mark.error, .item-mark.active')).toHaveCount(0)
      await expect(reply.locator('.waiting-copy')).toHaveCount(0)
      await expect(reply).toContainText(answer.content)
      await expect(page.locator('.message-item')).toHaveCount(2)
      if (!attempt) await page.reload()
    }
    expect(historyReads).toBe(race ? 3 : 2)
    expect(executions).toEqual([])
    expect(errors).toEqual([])
  })
}

test('older completed replies without activity metadata never show preparation or a made-up duration', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '旧记录验收', scope: 'general' }]
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '旧记录验收', scope: 'general' }
    else if (path.endsWith('/messages')) data = [{ role: 'user', content: '旧问题' },
      { role: 'assistant', runId: 'old-run', content: '旧回答仍在。' }]
    else if (path.endsWith('/101/run')) data = { runId: 'old-run', status: 'succeeded', result: { reply: '旧回答仍在。' } }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  const reply = page.locator('.message-item.assistant').first()
  await expect(reply.locator('.activity-summary')).toHaveText('处理完成')
  await expect(reply.locator('.activity-duration')).toHaveCount(0)
  await reply.locator('.activity-header').click()
  await expect(reply.locator('.waiting-copy')).toHaveText('该回复未保留处理明细。')
  await expect(reply).not.toContainText('正在准备')
  await expect(reply).not.toContainText('0 项活动')
})

test('an answer with unavailable verification shows a warning before and after reload', async ({ page }) => {
  await page.addInitScript(() => {
    const payload = btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))
    localStorage.setItem('token', `qa.${payload}.isolated-test`)
    localStorage.setItem('userId', '7')
  })
  const history = [{role:'user', content:'帮我总结下'}, {
    role:'assistant', content:'已读取部分正文的总结。', runId:'review-unavailable', runStatus:'succeeded',
    agentEvents:[
      {version:1,kind:'activity',id:'main/round_1/grounding',label:'自动核验未完成',status:'error',
        detail:'回答较长，超出本次自动核验范围。'},
      {version:1,kind:'status',status:'complete'},
    ],
  }]
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/agent/conversations')) data = [{conversationId:'101', title:'核验状态验收', scope:'general'}]
    else if (path.endsWith('/agent/conversations/101')) data = {conversationId:'101', title:'核验状态验收', scope:'general'}
    else if (path.endsWith('/messages')) data = history
    else if (path.endsWith('/101/run')) data = {runId:'review-unavailable', status:'succeeded', result:{reply:'已读取部分正文的总结。'}}
    else if (path.includes('/agent/runs')) data = {items:[],serverTime:new Date().toISOString()}
    await route.fulfill({json:{code:200,data}})
  })
  await page.goto('/ai-chat?conversationId=101')
  const answer = page.locator('.message-item.assistant').first()
  for (let attempt = 0; attempt < 2; attempt++) {
    await expect(answer.locator('.activity-summary')).toHaveText('回答已生成，核验未完成')
    await expect(answer.locator('.status-indicator')).toHaveClass(/warning/)
    await expect(answer.locator('.activity-header')).toHaveAttribute('aria-expanded', 'true')
    await expect(answer).toContainText('已读取部分正文的总结。')
    await expect(answer).toContainText('超出本次自动核验范围')
    if (!attempt) await page.reload()
  }
})

test('failed turns keep activities after reload and later successful replies', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    const payload = btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))
    localStorage.setItem('token', `qa.${payload}.isolated-test`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('nickName', '运行恢复验收')
  })
  const history = [
    { role: 'user', content: '对比两篇文章' },
    { role: 'assistant', content: '本次处理失败，已完成的活动保留在下方，可以继续提问。',
      runId: 'failed-run', runStatus: 'failed', runStartedAt: '2026-10-11T01:00:00Z', runFinishedAt: '2026-10-11T01:00:20Z',
      agentEvents: [
        { version: 1, kind: 'activity', id: 'a', label: '检索文章 A', status: 'done', timestamp: '2026-10-11T01:00:05Z' },
        { version: 1, kind: 'activity', id: 'b', label: '分析文章 B', status: 'error', timestamp: '2026-10-11T01:00:20Z' },
      ] },
    { role: 'user', content: '继续' },
    { role: 'assistant', content: '后续已整理完成。' },
  ]
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '失败运行验收', scope: 'general' }]
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '失败运行验收', scope: 'general' }
    else if (path.endsWith('/messages')) data = history
    else if (path.endsWith('/101/run')) data = { runId: 'later-run', status: 'succeeded', result: { reply: '后续已整理完成。' } }
    else if (path.includes('/agent/runs')) data = { items: [], serverTime: new Date().toISOString() }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  const failed = page.locator('.message-item.assistant').first()
  await expect(failed).toContainText('处理未完成')
  await expect(failed).toContainText('本次处理失败')
  await expect(failed).toContainText('检索文章 A')
  await expect(failed).toContainText('分析文章 B')
  await failed.locator('.activity-header').click()
  await expect(failed.locator('.activity-header')).toHaveAttribute('aria-expanded', 'false')
  await expect(failed.locator('.activity-reveal')).toHaveAttribute('aria-hidden', 'true')
  await expect(page.locator('.message-item')).toHaveCount(4)
  await page.reload()
  await expect(page.locator('.message-item')).toHaveCount(4)
  await expect(failed).toContainText('本次处理失败')
  await expect(failed.locator('.activity-header')).toHaveAttribute('aria-expanded', 'true')
  await expect(failed).toContainText('检索文章 A')
  await expect(failed).toContainText('分析文章 B')
  await expect(page.getByText('后续已整理完成。', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('expiration between history and run reads restores activities on the first refresh', async ({ page }) => {
  await page.addInitScript(() => {
    const payload = btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))
    localStorage.setItem('token', `qa.${payload}.isolated-test`)
    localStorage.setItem('userId', '7')
  })
  let reads = 0
  const failure = { role: 'assistant', content: '本次处理超时或执行连接中断，可以继续提问。',
    runId: 'expired-run', runStatus: 'expired', agentEvents: [
      { version: 1, kind: 'activity', id: 'search', label: '检索已完成', status: 'done' },
      { version: 1, kind: 'activity', id: 'main', label: '决定下一步', status: 'active' },
    ] }
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '超时验收', scope: 'general' }]
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '超时验收', scope: 'general' }
    else if (path.endsWith('/messages')) data = [{ role: 'user', content: '继续检索' }, ...(++reads > 1 ? [failure] : [])]
    else if (path.endsWith('/101/run')) data = { runId: 'expired-run', status: 'expired' }
    else if (path.includes('/agent/runs')) data = { items: [], serverTime: new Date().toISOString() }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  await expect(page.locator('.message-item')).toHaveCount(2)
  await expect(page.getByText('检索已完成', { exact: true })).toBeVisible()
  await expect(page.getByText('决定下一步', { exact: true })).toBeVisible()
  await expect(page.locator('.activity-item').last().locator('.item-mark')).toHaveClass(/error/)
  expect(reads).toBe(2)
})
