import { test, expect } from '@playwright/test'

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
