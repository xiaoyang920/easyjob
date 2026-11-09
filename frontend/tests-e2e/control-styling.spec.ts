import { test, expect, type Page, type Locator } from '@playwright/test'

test.use({ actionTimeout: 8000 })
const answer = '这是用于验证控件样式的回答，复制后应保留完整内容。'
async function fixture(page: Page, writing = false) {
  const errors: string[] = [], writes: any[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))}.controls`)
    localStorage.setItem('userId', '7')
    localStorage.setItem('easyjob:writing-conversation:7:42', '101')
  })
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    let data: any = []
    if (path.endsWith('/article/42/edit')) data = { articleId: '42', title: '写作控件验收', content: '<p>这是正文，编辑器工具栏保留独立样式。</p>', status: 0, revisionId: 'qa', lockVersion: 1 }
    else if (path.endsWith('/user/space/7')) data = { userId: '7', role: 0, status: 1 }
    else if (path.endsWith('/agent/library')) data = { rows: url.searchParams.get('scope') === 'general' ? [{ conversationId: '101', title: '控件验收', version: 1 }] : [], total: url.searchParams.get('scope') === 'general' ? 1 : 0 }
    else if (path.endsWith('/agent/conversations/101')) data = { conversationId: '101', title: '控件验收', version: 1 }
    else if (path.endsWith('/messages')) data = { items: [{ messageId: '1', role: 'assistant', content: answer, runId: '01b3e467-9daa-4ad1-b1cc-5ccfe70e38de' }], beforeCursor: '1', afterCursor: '1', hasOlder: !writing, hasNewer: false }
    else if (path.endsWith('/feedback') && route.request().method() === 'PUT') { writes.push(route.request().postDataJSON()); data = true }
    else if (path.endsWith('/feedback') || path.endsWith('/run')) data = null
    else if (path.endsWith('/questions')) data = { items: [], hasMore: false }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.endsWith('/unread-count') || path.endsWith('/total-unread-count')) data = 0
    await route.fulfill({ json: { code: 200, data } })
  })
  await page.goto(writing ? '/create-article?id=42' : '/ai-chat?conversationId=101')
  return { errors, writes }
}
async function paperButton(button: Locator) {
  await expect(button).toHaveCSS('appearance', 'none')
  await expect(button).toHaveCSS('border-radius', '999px')
  await expect(button).toHaveCSS('background-color', 'rgb(255, 253, 247)')
  await expect(button).toHaveCSS('border-top-style', 'solid')
  expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(32)
}

test('answer and history controls share paper styling, copy correctly and remain keyboard accessible', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const { errors, writes } = await fixture(page)
  const copy = page.getByRole('button', { name: '复制回答', exact: true })
  await paperButton(copy)
  await paperButton(page.getByRole('button', { name: '加载更早的消息', exact: true }))
  await copy.hover(); await expect(copy).toHaveCSS('background-color', 'rgb(233, 255, 179)')
  await copy.focus(); await expect(copy).toHaveCSS('outline-style', 'solid')
  await page.keyboard.press('Enter')
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(answer)
  await page.getByRole('button', { name: '有问题', exact: true }).click()
  const submit = page.getByRole('button', { name: '提交反馈', exact: true })
  expect(writes).toHaveLength(0)
  await expect(submit).toHaveAttribute('type', 'submit')
  await expect(submit).toHaveCSS('background-color', 'rgb(17, 17, 15)')
  await page.screenshot({ path: info.outputPath('answer-controls-desktop.png'), animations: 'disabled' })
  await submit.click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].rating).toBe('problem')
  expect(errors).toEqual([])
})

for (const width of [1440, 390]) {
  test(`fullscreen writing controls retain their theme outside #app at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 })
    const { errors } = await fixture(page, true)
    await expect(page.locator('[data-slate-editor]')).toContainText('工具栏保留独立样式')
    const fullscreenButton = page.locator('.article-rich-editor [data-menu-key="fullScreen"]')
    // WangEditor's own toolbar uses 0 8px, rather than the product button's 8px 14px.
    await expect(fullscreenButton).toHaveCSS('padding-left', '8px')
    await expect(fullscreenButton).toHaveCSS('padding-top', '0px')
    await fullscreenButton.click()
    const fullscreen = page.getByRole('dialog', { name: '全屏编辑正文', exact: true })
    await fullscreen.getByRole('button', { name: /问 AI/ }).click()
    const panel = page.locator('#writing-ai-panel')
    const copy = panel.getByRole('button', { name: '复制回答', exact: true })
    await paperButton(copy)
    expect(await copy.evaluate(el => el.closest('#app'))).toBeNull()
    await expect(copy).toBeInViewport()
    await copy.click()
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(answer)
    await expect(panel.getByRole('button', { name: '有帮助', exact: true })).toHaveCSS('border-radius', '999px')
    await page.screenshot({ path: info.outputPath(`writing-controls-${width}.png`), animations: 'disabled' })
    await panel.getByRole('button', { name: '收起 AI 写作助手', exact: true }).click()
    await fullscreen.getByRole('button', { name: '退出全屏' }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
    expect(errors).toEqual([])
  })
}

test('rename and delete dialogs share the project theme and cancel without submitting changes', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const { errors } = await fixture(page)
  const menu = page.getByRole('button', { name: '对话「控件验收」的更多操作', exact: true })
  await menu.click()
  await page.getByRole('menuitem').filter({ hasText: '重命名对话' }).click()
  let dialog = page.getByRole('dialog', { name: '重命名对话', exact: true })
  await expect(dialog.locator('.el-message-box')).toHaveCSS('background-color', 'rgb(255, 253, 247)')
  await expect(dialog.locator('.el-message-box')).toHaveCSS('border-radius', '20px')
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toHaveCSS('background-color', 'rgb(17, 17, 15)')
  await expect(dialog.locator('.el-input__wrapper')).toHaveCSS('background-color', 'rgb(242, 239, 231)')
  await page.screenshot({ path: info.outputPath('rename-dialog.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await page.setViewportSize({ width: 390, height: 640 })
  await menu.click(); await page.getByRole('menuitem').filter({ hasText: '删除对话' }).click()
  dialog = page.getByRole('dialog', { name: '删除对话', exact: true })
  await expect(dialog.getByRole('button', { name: '保留对话', exact: true })).toBeInViewport()
  const box = (await dialog.locator('.el-message-box').boundingBox())!
  expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(390)
  await dialog.getByRole('button', { name: '保留对话', exact: true }).click()
  await expect(page.locator('.conversation-item')).toHaveCount(1)
  expect(errors).toEqual([])
})
