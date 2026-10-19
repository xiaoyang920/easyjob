import { test, expect, type Page } from '@playwright/test'

test.use({ actionTimeout: 8000 })
const content = '<p>正文第一段。</p>' + Array.from({ length: 32 }, (_, i) => `<p>第 ${i + 1} 段，长文章内容保持不变。</p>`).join('') + '<pre><code class="language-go">func main() { println("hello") }</code></pre><p>正文最后一段。</p>'

async function openEditor(page: Page, draftDialog = false) {
  await page.addInitScript(() => {
    const payload = btoa(JSON.stringify({ sub: '7', exp: Math.floor(Date.now() / 1000) + 3600 }))
    localStorage.setItem('token', `qa.${payload}.fullscreen-test`)
    localStorage.setItem('userId', '7')
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    const pending = { runId: 'fullscreen-qa', draftHash: 'a'.repeat(64), title: '全屏编辑测试', draft: content, contentFormat: 'html' }
    if (path.endsWith('/article/42/edit')) data = { articleId: '42', title: pending.title, content, status: 0, revisionId: 'qa-revision', lockVersion: 1 }
    else if (path.endsWith('/agent/library')) data = { rows: [{ conversationId: '101', title: pending.title }], total: 1 }
    else if (path.endsWith('/messages')) data = [{ role: 'assistant', content, isDraft: true, interrupted: true, interruptPayload: pending }]
    else if (path.endsWith('/101/run')) data = { runId: pending.runId, status: 'awaiting_approval', result: { interrupted: pending } }
    else if (path.includes('/agent/runs')) data = { items: [] }
    return route.fulfill({ json: { code: 200, data } })
  })
  await page.goto(draftDialog ? '/ai-chat?conversationId=101' : '/create-article?id=42')
  if (draftDialog) await page.getByRole('button', { name: '直接编辑', exact: true }).click()
  const editor = page.locator('.article-rich-editor [data-slate-editor]')
  await expect(editor).toContainText('正文第一段。')
  return editor
}

for (const draftDialog of [false, true]) {
  for (const width of [1440, 390]) {
    test(`fullscreen covers background, preserves edits and exits by button/Esc in ${draftDialog ? 'draft dialog' : 'article editor'} at ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 900 })
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      const editor = await openEditor(page, draftDialog)
      const editorId = await editor.getAttribute('id')
      const originalOverflow = await page.evaluate(() => [document.body.style.overflow, document.documentElement.style.overflow])
      const codeColor = await editor.locator('pre').evaluate(el => getComputedStyle(el).backgroundColor)
      const keyword = editor.locator('pre .token.keyword').first()
      await expect(keyword).toHaveCSS('color', 'rgb(180, 167, 255)')
      const toggle = page.locator('.article-rich-editor .toolbar [data-menu-key="fullScreen"]')
      await toggle.click()
      const fullscreen = page.getByRole('dialog', { name: '全屏编辑正文', exact: true })
      await expect(fullscreen).toBeVisible()
      expect(await fullscreen.evaluate(el => el.parentElement === document.body)).toBe(true)
      await expect.poll(() => page.locator('#app').evaluate(el => el.inert)).toBe(true)
      const bounds = await fullscreen.boundingBox()
      expect(bounds!.x).toBe(0); expect(bounds!.y).toBe(0)
      expect(bounds!.width).toBe(width); expect(bounds!.height).toBe(900)
      // Check actual hit testing, so invisible/covered settings cannot pass as "hidden".
      expect(await fullscreen.evaluate(el => [[10, 10], [innerWidth - 12, 120], [innerWidth - 30, 450], [innerWidth / 2, innerHeight - 12]].every(([x, y]) => el.contains(document.elementFromPoint(x, y))))).toBe(true)
      await page.keyboard.press('Shift+Tab')
      expect(await fullscreen.evaluate(el => el.contains(document.activeElement))).toBe(true)
      await expect(editor).toHaveAttribute('id', editorId!)
      expect(await editor.locator('pre').evaluate(el => getComputedStyle(el).backgroundColor)).toBe(codeColor)
      await expect(keyword).toHaveCSS('color', 'rgb(180, 167, 255)')
      await editor.locator('p').first().click()
      await page.keyboard.press('End')
      await page.keyboard.type(' 全屏修改保留。')
      await expect(editor.locator('p').first()).toContainText('全屏修改保留。')
      await fullscreen.locator('.w-e-scroll').evaluate(el => { el.scrollTop = el.scrollHeight })
      await expect(editor.locator('p').last()).toBeInViewport()
      const exit = fullscreen.getByRole('button', { name: '退出全屏' })
      await expect(exit).toBeInViewport()
      await page.screenshot({ path: info.outputPath(`fullscreen-${draftDialog ? 'dialog' : 'article'}-${width}.png`), animations: 'disabled' })
      await exit.click()
      await expect(fullscreen).toHaveCount(0)
      await expect(page.locator('.w-e-full-screen-container')).toHaveCount(0)
      expect(await page.evaluate(() => [document.body.style.overflow, document.documentElement.style.overflow])).toEqual(originalOverflow)
      expect(await page.locator('#app').evaluate(el => el.inert)).toBe(false)
      await expect(editor).toHaveAttribute('id', editorId!)
      await expect(editor.locator('p').first()).toContainText('全屏修改保留。')
      await toggle.click()
      await expect(fullscreen).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(fullscreen).toHaveCount(0)
      if (draftDialog) {
        await expect(page.getByRole('dialog', { name: '编辑草稿', exact: true })).toBeVisible()
        await page.getByRole('button', { name: '应用修改', exact: true }).click()
        await expect(page.locator('.draft-review-body')).toContainText('全屏修改保留。')
      }
      expect(errors).toEqual([])
    })
  }
}

test('leaving the page during fullscreen restores background and page scrolling', async ({ page }) => {
  await openEditor(page)
  const before = await page.evaluate(() => [document.body.style.overflow, document.documentElement.style.overflow])
  await page.locator('.article-rich-editor [data-menu-key="fullScreen"]').click()
  await expect(page.getByRole('dialog', { name: '全屏编辑正文', exact: true })).toBeVisible()
  await page.evaluate(() => { history.pushState({}, '', '/'); window.dispatchEvent(new PopStateEvent('popstate')) })
  await expect(page.locator('.article-rich-editor')).toHaveCount(0)
  expect(await page.evaluate(() => [document.body.style.overflow, document.documentElement.style.overflow])).toEqual(before)
  expect(await page.locator('#app').evaluate(el => el.inert)).toBe(false)
})
