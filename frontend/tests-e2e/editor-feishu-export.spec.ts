import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const nativeReturn = JSON.parse(readFileSync(new URL('./fixtures/feishu-website-return.json', import.meta.url), 'utf8'))

test('normal copy provides a native Feishu record and an equivalent HTML fallback without changing the source', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/tests-e2e/fixtures/editor-feishu-export.html')
  const editor = page.locator('[data-slate-editor]')
  await expect(editor).toContainText('正文第二行')
  const source = () => editor.evaluate(el => [...el.children].map(block => ({
    tag: block.tagName, style: block.getAttribute('style'), text: block.textContent,
    marks: [...block.querySelectorAll('strong,em,u,s,code,a')].map(mark => ({ tag: mark.tagName, text: mark.textContent, href: mark.getAttribute('href') })),
  })))
  const before = await source()
  await editor.click(); await page.keyboard.press('Control+a'); await page.keyboard.press('Control+c')
  const html = await page.evaluate(async () => {
    const items = await navigator.clipboard.read(), item = items.find(item => item.types.includes('text/html'))!
    return (await item.getType('text/html')).text()
  })
  const record = await page.evaluate(html => {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    return JSON.parse(doc.querySelector('[data-lark-record-data]')!.getAttribute('data-lark-record-data')!)
  }, html)
  const nodes = Object.values(record.recordMap) as any[], textNodes = nodes.filter(item => item.snapshot.type !== 'page')
  expect(textNodes.slice(0, 5).map(node => node.snapshot.text.initialAttributedTexts.text['0'])).toEqual(['网站复制到飞书验证', '二级标题', '正文第一行', '正文第二行', '正文第三行'])
  expect(textNodes[1].snapshot.parent_id).toBe(textNodes[0].id)
  expect(textNodes[2].snapshot.parent_id).toBe(textNodes[1].id)
  expect(textNodes[3].snapshot.parent_id).toBe(textNodes[2].id)
  expect(textNodes[4].snapshot.parent_id).toBe(textNodes[1].id)
  expect(textNodes.slice(0, 5).map(node => node.snapshot.text_indent)).toEqual([0, 0, 1, 1, 1])
  expect(Object.values(textNodes[5].snapshot.text.apool.numToAttrib)).toContainEqual(['link', 'https%3A%2F%2Fexample.org%2Fguide'])
  expect(html).toContain('data-ej-feishu-copy="1"')
  expect(await source()).toEqual(before)
  // Return paste uses the original Slate fragment, not the outbound metadata.
  await page.keyboard.press('Control+End'); await page.keyboard.press('Enter'); await page.keyboard.press('Control+v')
  await expect(editor.locator('h1')).toHaveCount(2)
  await expect(editor.locator('p').filter({ hasText: '正文第二行' }).last()).toHaveCSS('margin-left', '96px')
  await expect(editor.locator('p').filter({ hasText: '正文第二行' }).last()).toHaveCSS('text-indent', '32px')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('h1')).toHaveCount(1)
  // HTML-only transfers must use our original styles rather than importing the hidden metadata as visible content.
  await page.keyboard.press('Control+End')
  await editor.evaluate((el, html) => {
    const data = new DataTransfer()
    data.setData('text/html', html.replace(/\sdata-slate-fragment="[^"]*"/g, ''))
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
    el.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: data, bubbles: true, cancelable: true }))
  }, html)
  await expect(editor.locator('h1')).toHaveCount(2)
  await expect(editor.locator('p').filter({ hasText: '正文第二行' }).last()).toHaveCSS('margin-left', '96px')
  await expect(editor.locator('p').filter({ hasText: '正文第二行' }).last()).toHaveCSS('text-indent', '32px')
  await expect(editor).not.toContainText('recordMap')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('h1')).toHaveCount(1)
})

test('native Feishu clipboard returns through a real paste with its hierarchy and marks', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.goto('/tests-e2e/fixtures/editor-feishu-export.html')
  const editor = page.locator('[data-slate-editor]')
  await expect(editor).toContainText('正文第二行')
  await editor.click(); await page.keyboard.press('Control+End')
  await page.evaluate(async data => {
    const metadata = document.createElement('span')
    metadata.className = 'lark-record-clipboard'
    metadata.setAttribute('data-lark-record-data', data['docx/record'])
    await navigator.clipboard.write([new ClipboardItem({
      'text/html': new Blob([data['text/html'] + metadata.outerHTML], { type: 'text/html' }),
      'text/plain': new Blob([data['text/plain']], { type: 'text/plain' }),
    })])
  }, nativeReturn)
  await page.keyboard.press('Control+v')
  await expect(editor.locator('h1')).toHaveCount(2)
  await expect(editor.locator('h2')).toHaveCount(2)
  await expect(editor.locator('p').filter({ hasText: '正文第二行' }).last()).toHaveCSS('margin-left', '96px')
  await expect(editor.locator('p').filter({ hasText: '正文第二行' }).last()).toHaveCSS('text-indent', '32px')
  await expect(editor.locator('a[href="https://example.org/guide"]')).toHaveCount(2)
  await expect(editor.locator('strong').filter({ hasText: '粗体' })).toHaveCount(2)
  await expect(editor).not.toContainText('recordMap')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('h1')).toHaveCount(1)
  await page.keyboard.press('Control+y')
  await expect(editor.locator('h1')).toHaveCount(2)
})
