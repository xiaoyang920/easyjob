import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`long execution plans expand completely and restore after reload at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.addInitScript(() => {
      localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
      localStorage.setItem('userId', '7')
      localStorage.setItem('nickName', '计划展示验收')
    })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const label = '核实图片中的角色与原始发布来源，比较服饰、发型及构图；'.repeat(12)
      + '\n最后核对纳兰嫣然的设定，并说明不能确认的部分。'
    const history = [{ role: 'user', content: '核实图片出处' }, {
      role: 'assistant', content: '当前未能确认出处。', runId: 'plan-qa', runStatus: 'failed',
      agentEvents: [
        { version: 1, kind: 'plan', tasks: [
          { id: 'source', label, role: 'search', stage: 1 },
          { id: 'notes', label: '核对来源', role: 'analysis', stage: 2 },
        ] },
        { version: 1, kind: 'activity', id: 'source/task', taskId: 'source', step: 'task', label: '检索资料', status: 'done' },
      ],
    }]
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: any = []
      if (path.endsWith('/user/space/7')) data = { userId: '7', nickName: '计划展示验收', role: 2, status: 1 }
      else if (path.endsWith('/agent/library')) data = { rows: [{ conversationId: '101', title: '计划展示验收', scope: 'general' }], total: 1 }
      else if (path.endsWith('/agent/conversations')) data = [{ conversationId: '101', title: '计划展示验收', scope: 'general' }]
      else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '计划展示验收', scope: 'general' }
      else if (path.endsWith('/messages')) data = history
      else if (path.endsWith('/101/run')) data = { status: 'idle' }
      else if (path.endsWith('/agent/run-overview')) data = { items: [] }
      else if (path.endsWith('/questions')) data = { items: [], hasMore: false }
      else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
      await route.fulfill({ json: { code: 200, data } })
    })
    await page.goto('/ai-chat?conversationId=101')
    const plan = page.locator('.task-plan')
    const full = plan.getByRole('button', { name: '展开完整计划', exact: true })
    await expect(full).toBeVisible()
    await expect(plan.locator('.plan-text').first()).toHaveText(Array.from(label).slice(0, 160).join('') + '…')
    await expect(plan.getByRole('button')).toHaveCount(1)
    await full.click()
    const collapse = plan.getByRole('button', { name: '收起', exact: true })
    await expect(collapse).toHaveAttribute('aria-expanded', 'true')
    await expect(plan.locator('.plan-text').first()).toHaveText(label)
    const controlId = await collapse.getAttribute('aria-controls')
    await expect(page.locator(`[id="${controlId}"]`)).toHaveCount(1)
    const size = await plan.locator('.plan-text').first().evaluate(el => ({
      width: el.clientWidth, scrollWidth: el.scrollWidth, height: el.clientHeight, scrollHeight: el.scrollHeight,
    }))
    expect(size.scrollWidth).toBeLessThanOrEqual(size.width + 1)
    expect(size.scrollHeight).toBeLessThanOrEqual(size.height + 1)
    if (width === 1440) await page.screenshot({ path: '../temp/agent-plan-expanded-desktop.png' })
    await collapse.click()
    await expect(plan.getByRole('button', { name: '展开完整计划', exact: true })).toHaveAttribute('aria-expanded', 'false')
    await page.reload()
    await page.getByRole('button', { name: '展开完整计划', exact: true }).click()
    await expect(page.locator('.plan-text').first()).toHaveText(label)
    expect(errors).toEqual([])
  })
}
