import { test, expect, type Page } from '@playwright/test'

async function sidebar(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('nickName', '界面验收')
  })
  let conversations = [
    { conversationId: '101', title: '聊聊 Agent 的工具权限', isPinned: 0, metadataVersion: 0, updateTime: '2026-10-17T10:00:00' },
    { conversationId: '102', title: 'ES 中文检索与同义词应该如何配置', isPinned: 0, metadataVersion: 0, updateTime: '2026-10-16T10:00:00' },
    { conversationId: '103', title: '向量化线程池参数', isPinned: 1, metadataVersion: 0, updateTime: '2026-10-15T10:00:00' },
    { conversationId: '201', title: '对比两篇缓存一致性文章', isPinned: 0, metadataVersion: 0, updateTime: '2026-10-17T09:00:00', originArticleId: '42', originArticleTitle: 'Redis 缓存一致性实践' },
  ]
  const edits: any[] = [], deletes: string[] = []
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    const id = path.match(/\/agent\/conversations\/(\d+)$/)?.[1]
    let data: any = []
    if (path.endsWith('/agent/library')) {
      const rows = conversations.filter(conv => (url.searchParams.get('scope') === 'article') === !!conv.originArticleId)
        .filter(conv => conv.title.includes(url.searchParams.get('keyword') || ''))
        .sort((a, b) => b.isPinned - a.isPinned || b.updateTime.localeCompare(a.updateTime))
      data = { rows, total: rows.length }
    } else if (id) {
      const conv = conversations.find(conv => conv.conversationId === id)!
      if (route.request().method() === 'PATCH') {
        const edit = route.request().postDataJSON(); expect(edit.version).toBe(conv.metadataVersion); edits.push(edit)
        Object.assign(conv, { title: edit.title ?? conv.title, isPinned: edit.pinned === undefined ? conv.isPinned : Number(edit.pinned), metadataVersion: conv.metadataVersion + 1 })
        data = { version: conv.metadataVersion }
      } else if (route.request().method() === 'DELETE') {
        deletes.push(id); conversations = conversations.filter(conv => conv.conversationId !== id)
      } else data = conv
    } else if (path.endsWith('/messages')) data = [
      { role: 'user', content: '检索任务能调用保存文章的工具吗？' },
      { role: 'assistant', content: '检索任务只开放搜索工具。后端会校验工具权限，发现越权调用后拒绝执行，再根据任务状态决定重试或调整策略。\n\n你可以继续追问，也可以开启一个新的话题。' },
    ]
    else if (path.endsWith('/run')) data = null
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/ai-chat?conversationId=101')
  await expect(page.locator('.conversation-item')).toHaveCount(3)
  return { edits, deletes }
}

test('pin menu explains its scope, persists ordering and does not switch the active chat', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message))
  const { edits } = await sidebar(page)
  const target = page.locator('.conversation-item').filter({ hasText: 'ES 中文检索与同义词' })
  await target.locator('.conv-menu-trigger').click()
  await expect(page.getByRole('menuitem', { name: /置顶对话/ })).toContainText('固定在普通聊天顶部')
  await expect(page.locator('.conversation-item.active .conv-title')).toHaveText('聊聊 Agent 的工具权限')
  await page.getByRole('menuitem', { name: /置顶对话/ }).click()
  await expect(target.locator('.conv-pinned-badge')).toHaveText('已置顶')
  await expect(page.locator('.conversation-item').first()).toContainText('ES 中文检索与同义词')
  expect(edits[0]).toEqual({ pinned: true, version: 0 })
  await page.reload()
  await expect(target.locator('.conv-pinned-badge')).toBeVisible()
  await target.locator('.conv-menu-trigger').click()
  await expect(page.getByRole('menuitem', { name: /取消置顶/ })).toContainText('恢复按最近更新排序')
  await page.getByRole('menuitem', { name: /取消置顶/ }).click()
  await expect(target.locator('.conv-pinned-badge')).toHaveCount(0)
  await expect(page.locator('.conversation-item').first()).toContainText('向量化线程池参数')
  expect(edits[1]).toEqual({ pinned: false, version: 1 })
  expect(errors).toEqual([])
})

test('delete requires confirmation and search can be cleared without losing selection', async ({ page }) => {
  const { deletes } = await sidebar(page)
  await page.getByRole('textbox', { name: '搜索对话' }).fill('不存在')
  await expect(page.locator('.conversation-item')).toHaveCount(0)
  await expect(page.getByText('没有找到匹配的对话', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '清空对话搜索' }).click()
  await expect(page.locator('.conversation-item')).toHaveCount(3)
  await expect(page.locator('.conversation-item.active')).toContainText('聊聊 Agent 的工具权限')
  const target = page.locator('.conversation-item').filter({ hasText: 'ES 中文检索与同义词' })
  await target.locator('.conv-menu-trigger').click(); await page.getByRole('menuitem', { name: /删除对话/ }).click()
  await expect(page.locator('.el-message-box')).toContainText('删除后将无法恢复')
  expect(deletes).toEqual([])
  await page.locator('.el-message-box').getByRole('button', { name: '保留对话' }).click()
  await expect(target).toBeVisible(); expect(deletes).toEqual([])
  await target.locator('.conv-menu-trigger').click(); await page.getByRole('menuitem', { name: /删除对话/ }).click()
  await page.locator('.el-message-box').getByRole('button', { name: '删除对话', exact: true }).click()
  await expect(target).toHaveCount(0); expect(deletes).toEqual(['102'])
})

test('sidebar menus work with keyboard and remain readable on narrow screens', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 }); await sidebar(page)
  await page.getByRole('button', { name: '文章问答', exact: true }).click()
  await expect(page.getByText('来源：Redis 缓存一致性实践')).toBeVisible()
  const target = page.locator('.conversation-item').filter({ hasText: '聊聊 Agent 的工具权限' })
  await target.locator('.conv-menu-trigger').focus(); await page.keyboard.press('Enter')
  await expect(page.getByRole('menuitem', { name: /置顶对话/ })).toBeVisible()
  await page.screenshot({ path: '../logs/agent-ui-desktop.png', animations: 'disabled' })
  await page.keyboard.press('Escape'); await expect(target.locator('.conv-menu-trigger')).toBeFocused()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await page.getByRole('button', { name: /返回对话列表/ }).click()
  const memoryBounds = await page.getByRole('link', { name: /长期记忆/ }).boundingBox()
  expect(memoryBounds!.y + memoryBounds!.height).toBeLessThanOrEqual(844)
  const narrowTarget = page.locator('.conversation-item').filter({ hasText: 'ES 中文检索与同义词' })
  await narrowTarget.locator('.conv-menu-trigger').click()
  const menu = page.locator('.ai-conversation-menu:visible')
  await expect(menu).toBeVisible()
  const bounds = await menu.boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '../logs/agent-ui-mobile.png', animations: 'disabled' })
})
