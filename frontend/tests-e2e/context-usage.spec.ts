import { test, expect, type Page } from '@playwright/test'

const usage = (usedTokens: number | null) => ({ scope: 'main_request', estimated: true, usedTokens,
  limitTokens: 262144, inputBudgetTokens: 245760, measuredAt: '2026-10-29T01:00:00Z' })

async function setup(page: Page) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
  })
  const state = { used: 65536, reads: 0 }
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/chat/stream')) {
      state.used = 131072
      return route.fulfill({ contentType: 'text/event-stream', body:
        `data:__CONV_ID__:101\n\ndata:__AGENT_EVENT__:${JSON.stringify({ version: 1, kind: 'context_usage', usage: usage(state.used) })}\n\ndata:__REPLY__:{"content":"已收到"}\n\ndata:[DONE]\n\n` })
    }
    if (path.endsWith('/context-usage')) { state.reads++; data = usage(path.includes('/conversations/') ? state.used : null) }
    else if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '上下文验收', scope: 'general' }]
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '上下文验收', scope: 'general' }
    else if (path.endsWith('/messages')) data = [{ role: 'user', content: '测试历史' }, { role: 'assistant', content: '历史回答' }]
    else if (path.endsWith('/run')) data = { status: 'idle' }
    else if (path.endsWith('/run-overview')) data = { items: [] }
    else if (path.endsWith('/questions')) data = { items: [], hasMore: false }
    else if (path.endsWith('/unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  return { state, errors }
}

for (const width of [1440, 390]) {
  test(`context meter restores measured usage and fits ${width}px`, async ({ page }) => {
    const { state, errors } = await setup(page)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/ai-chat?conversationId=101')
    const meter = page.getByRole('button', { name: '上下文已用 25%' })
    await expect(meter).toBeVisible()
    await meter.click()
    const details = page.getByTestId('context-details')
    await expect(details).toContainText('剩余 75%')
    await expect(details).toContainText('已用 64k，共 256k Token')
    await expect(details).toContainText('估算值')
    const box = await details.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await expect(page.locator('.context-usage-popover')).toHaveCSS('opacity', '1')
    await page.screenshot({ path: `../temp/context-usage-${width}.png` })
    await page.keyboard.press('Escape')
    await expect(details).not.toBeVisible()
    const before = state.reads
    await page.locator('textarea').last().fill('未发送的内容不会计入')
    await expect(meter).toBeVisible()
    expect(state.reads).toBe(before)
    await page.reload()
    await expect(meter).toBeVisible()
    expect(errors).toEqual([])
  })
}

test('new chat stays unknown until streamed request usage arrives', async ({ page }) => {
  const { errors } = await setup(page)
  await page.goto('/ai-chat')
  const meter = page.getByRole('button', { name: '上下文用量：待计算' })
  await meter.hover()
  await expect(page.getByTestId('context-details')).toContainText('上下文上限 256k')
  await page.locator('textarea').last().fill('你好')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(page.getByRole('button', { name: '上下文已用 50%' })).toBeVisible()
  await expect(page.locator('.message-item.assistant').last()).toContainText('已收到')
  await page.reload()
  await expect(page.getByRole('button', { name: '上下文已用 50%' })).toBeVisible()
  expect(errors).toEqual([])
})

test('a late previous-conversation response cannot replace the selected context', async ({ page }) => {
  await setup(page)
  let release!: () => void
  let requested!: () => void
  const received = new Promise<void>(resolve => { requested = resolve })
  const delayed = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/agent/conversations/101/context-usage', async route => {
    requested(); await delayed
    await route.fulfill({ json: { code: 200, data: usage(200000) } }).catch(() => {})
  })
  await page.goto('/ai-chat?conversationId=101')
  await received
  await page.getByRole('button', { name: /开启新对话/ }).click()
  await expect(page.getByRole('button', { name: '上下文用量：待计算' })).toBeVisible()
  release()
  await page.getByRole('button', { name: '上下文用量：待计算' }).hover()
  await expect(page.getByTestId('context-details')).toContainText('上下文上限 256k')
  await expect(page.getByTestId('context-details')).not.toContainText('76%')
})
