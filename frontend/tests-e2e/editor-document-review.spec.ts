import { test, expect, type Page } from '@playwright/test'

async function fixture(page: Page, options: { long?: boolean; category?: boolean; delayed?: boolean } = {}) {
  const writes: any[] = [], errors: string[] = []
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('userId', '7')
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({ sub: '7', exp: Date.now() / 1000 + 3600 }))}.document-review`)
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/article/42' && route.request().method() === 'PUT') {
      writes.push(route.request().postDataJSON())
      if (options.delayed && writes.length === 1) await gate
      return route.fulfill({ json: { code: 200, data: { revisionId: `r${writes.length + 1}`, lockVersion: writes.length + 1, revisionState: 0 } } })
    }
    let data: any = []
    if (path.endsWith('/article/42/edit')) data = {
      articleId: '42', title: '文档验收', summary: '保留摘要', categoryId: options.category === false ? '' : '1',
      content: '<h1>开篇标题</h1><p>保留开头</p>' + (options.long ? Array.from({ length: 40 }, (_, i) => `<p>第 ${i + 1} 段文字</p>`).join('') : '') + '<p></p>',
      status: 0, revisionId: 'r1', lockVersion: 1,
    }
    else if (path.endsWith('/category/list')) data = [{ categoryId: '1', categoryName: '技术' }]
    else if (path.endsWith('/user/space/7')) data = { role: 0, status: 1 }
    else if (path.endsWith('/agent/run-overview')) data = { items: [] }
    else if (path.includes('unread-count')) data = 0
    return route.fulfill({ json: { code: 200, data } })
  })
  await page.goto('/edit-article?id=42')
  const editor = page.locator('[data-slate-editor]')
  await expect(editor).toContainText('保留开头')
  return { editor, writes, errors, release }
}

test('save response acknowledges only submitted content and Ctrl+S saves subsequent edits', async ({ page }) => {
  const { editor, writes, errors, release } = await fixture(page, { delayed: true })
  await editor.locator('p').last().click()
  await page.keyboard.insertText('第一轮内容')
  await page.keyboard.press('Control+s')
  await expect.poll(() => writes.length).toBe(1)
  await page.keyboard.insertText('请求途中继续写')
  release()
  await expect(page.locator('.autosave-status')).toContainText('新修改')
  expect(writes[0].content).not.toContain('请求途中继续写')
  await page.keyboard.press('Control+s')
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].content).toContain('请求途中继续写')
  expect(writes[1].expectedLockVersion).toBe(2)
  await expect(page.locator('.autosave-status')).toContainText('已保存')
  expect(errors).toEqual([])
})

test('title composition does not move focus; missing category focuses the visible settings without sending', async ({ page }) => {
  const { writes, errors } = await fixture(page, { category: false })
  await page.clock.install()
  const title = page.locator('.title-input')
  await title.focus()
  await title.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true, keyCode: 229 })
  await expect(title).toBeFocused()
  await title.fill('有修改的标题')
  await page.clock.fastForward(5500)
  await expect(page.locator('.autosave-status')).toContainText('选择分类')
  await page.locator('.autosave-status').click()
  await expect(page.locator('.editor-sidebar')).toBeVisible()
  await expect(page.locator('.editor-sidebar .el-select')).toBeInViewport()
  expect(writes).toEqual([])
  expect(errors).toEqual([])
})

test('slash keyboard wrap reaches final item and undo preserves the command and surrounding document', async ({ page }) => {
  const { editor, errors } = await fixture(page)
  await editor.locator('p').last().click()
  await page.keyboard.press('Control+z')
  await expect(editor).toContainText('保留开头')
  await editor.locator('p').last().click()
  await page.keyboard.type('/')
  const menu = page.getByRole('listbox', { name: '插入块' })
  await expect(menu).toBeVisible()
  await page.keyboard.press('ArrowUp')
  await expect(menu.getByRole('option', { name: '分隔线', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(menu).toBeVisible()
  await page.keyboard.press('Enter')
  await expect(editor.locator('hr')).toHaveCount(1)
  await page.keyboard.press('Control+z')
  await expect(editor.locator('hr')).toHaveCount(0)
  await expect(editor.locator('p').last()).toHaveText('/')
  await expect(editor.locator('h1')).toHaveText('开篇标题')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('p').last()).toHaveText('')
  await expect(editor).toContainText('保留开头')
  expect(errors).toEqual([])
})

test('empty headings and lists return to prose, while soft breaks and code keep their structure', async ({ page }) => {
  const { editor, errors, writes } = await fixture(page)
  await editor.locator('p').last().click()
  await page.keyboard.type('/h1')
  await page.keyboard.press('Enter')
  await expect(editor.locator('h1')).toHaveCount(2)
  await page.keyboard.press('Enter')
  await expect(editor.locator('h1')).toHaveCount(1)
  await page.keyboard.type('/bullet')
  await page.keyboard.press('Enter')
  await page.keyboard.insertText('列表内容')
  await page.keyboard.press('Enter')
  await page.keyboard.press('Enter')
  await page.keyboard.insertText('退出列表后的正文')
  await expect(editor.locator('p').last()).toHaveText('退出列表后的正文')
  await page.keyboard.press('Shift+Enter')
  await page.keyboard.insertText('软换行')
  await expect(editor.locator('p').last()).toContainText('退出列表后的正文')
  await expect(editor.locator('p').last()).toContainText('软换行')
  await page.keyboard.press('Enter')
  await page.keyboard.type('/code')
  await page.keyboard.press('Enter')
  await page.keyboard.type('a/b')
  await expect(editor.locator('pre')).toContainText('a/b')
  await expect(page.getByRole('listbox', { name: '插入块' })).toBeHidden()
  await page.keyboard.press('Control+s')
  await expect.poll(() => writes.length).toBeGreaterThan(0)
  expect(writes.at(-1).content).toMatch(/退出列表后的正文(?:<br\s*\/?>|\n)软换行/)
  expect(errors).toEqual([])
})

for (const width of [1440, 390]) {
  test(`long document toolbar remains visible and dropdowns can be clicked at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 })
    const { editor, errors } = await fixture(page, { long: true })
    await editor.locator('p').nth(15).click()
    const toolbar = page.locator('.article-rich-editor .toolbar')
    await expect(toolbar).toBeInViewport()
    const hit = await toolbar.evaluate(el => {
      const rect = el.getBoundingClientRect()
      return { accessible: el.contains(document.elementFromPoint(rect.x + 30, rect.y + 15)), width: document.documentElement.scrollWidth, viewport: innerWidth }
    })
    expect(hit.accessible).toBe(true)
    expect(hit.width).toBeLessThanOrEqual(hit.viewport)
    await toolbar.locator('[data-menu-key="group-more"]').click()
    const underline = toolbar.locator('[data-menu-key="underline"]')
    await expect(underline).toBeVisible()
    await underline.click()
    await page.keyboard.type('格式验收')
    await expect(editor.locator('u')).toContainText('格式验收')
    await page.screenshot({ path: info.outputPath(`document-reviewed-${width}.png`) })
    expect(errors).toEqual([])
  })
}
