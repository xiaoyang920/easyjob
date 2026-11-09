import { test, expect, type Page, type Locator } from '@playwright/test'

const initial = '<h1>一级标题</h1><h2>二级标题</h2><p><span style="font-size:12px;">小号文字</span></p><p><span style="font-size:48px;">大号文字</span></p><p style="text-indent:64px;line-height:2;text-align:right;"><span style="font-size:32px;color:rgb(30,60,90);background-color:#ffeeaa;"><strong><u>手动格式示例</u></strong></span></p>'
async function fixture(page: Page) {
  let content = initial
  const writes: any[] = []
  await page.addInitScript(() => {
    localStorage.setItem('userId','7')
    localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Date.now()/1000+3600}))}.format`)
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/42') && route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body); content = body.content
      data = {revisionId:'r2',lockVersion:2,revisionState:0}
    } else if (path.endsWith('/article/42/edit')) data = {articleId:'42',title:'格式一致性',content,categoryId:'1',status:0,revisionId:'r1',lockVersion:1}
    else if (path.endsWith('/article/detail/42')) data = {articleId:'42',title:'格式一致性',content,canReadFull:true,authorId:'7',authorName:'示例',tags:[]}
    else if (path.endsWith('/agent/run-overview')) data = {items:[]}
    else if (path.includes('unread-count')) data = 0
    else if (path.includes('/comment/')) data = {records:[],total:0,pages:1,nextCursor:''}
    else if (path.startsWith('/api/reading/')) data = {sessionId:'qa',sessionToken:'qa',level:0,totalSeconds:0,rules:[]}
    return route.fulfill({json:{code:200,data}})
  })
  await page.goto('/edit-article?id=42')
  await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
  return {editor:page.locator('[data-slate-editor]'),writes}
}
async function caret(block: Locator) {
  await block.evaluate(el => {
    el.closest<HTMLElement>('[data-slate-editor]')!.focus()
    const leaf = el.querySelector('[data-slate-string]')!.firstChild!
    const range = document.createRange(); range.setStart(leaf,0); range.collapse(true)
    const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
}
async function formatting(root: Locator) {
  return root.evaluate(el => {
    const paragraph = [...el.querySelectorAll('p')].find(node => node.textContent === '手动格式示例')!
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT), text = walker.nextNode()!
    let node = text.parentElement!, background = 'rgba(0, 0, 0, 0)'
    const style = getComputedStyle(node)
    while (node !== paragraph) {
      const value = getComputedStyle(node).backgroundColor
      if (value !== 'rgba(0, 0, 0, 0)') { background = value; break }
      node = node.parentElement!
    }
    const block = getComputedStyle(paragraph)
    const heading = getComputedStyle(el.querySelector('h2')!)
    return {fontSize:style.fontSize,fontFamily:style.fontFamily,color:style.color,weight:style.fontWeight,background,indent:block.textIndent,lineHeight:block.lineHeight,align:block.textAlign,paragraphMargin:block.marginBottom,
      headingFont:heading.fontSize,headingHeight:heading.lineHeight,headingMargin:heading.marginTop,headingIndent:heading.marginInlineStart,headingBorder:heading.borderBottomWidth}
  })
}
for (const width of [1440,390]) {
  test(`fixed Tab stops and author formatting survive save, reopen and reading at ${width}px`, async ({page},info) => {
    await page.setViewportSize({width,height:1000})
    const {editor,writes} = await fixture(page)
    for (const text of ['小号文字','大号文字']) {
      const paragraph = editor.locator('p').filter({hasText:text})
      await caret(paragraph); await page.keyboard.press('Tab')
      await expect(paragraph).toHaveCSS('text-indent','32px')
    }
    const heading = editor.locator('h2')
    await caret(heading); await page.keyboard.press('Tab')
    await expect(heading).toHaveCSS('text-indent','0px')
    await expect(heading).toHaveCSS('margin-left','32px')
    const big = editor.locator('p').filter({hasText:'大号文字'})
    await caret(big)
    await page.keyboard.press('Tab'); await expect(big).toHaveCSS('margin-left','32px')
    await expect(big).toHaveCSS('text-indent','32px')
    await page.keyboard.press('Shift+Tab'); await expect(big).toHaveCSS('text-indent','0px')
    await page.keyboard.press('Tab'); await expect(big).toHaveCSS('text-indent','32px')
    const before = await formatting(editor)
    await page.keyboard.press('Control+s')
    await expect.poll(() => writes.length).toBe(1)
    expect(writes[0].content).toContain('font-size: 48px')
    expect(writes[0].content).toContain('text-indent: 32px')
    await expect(page.locator('.autosave-status')).toContainText('已保存')
    await page.reload()
    await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
    expect(await formatting(editor)).toEqual(before)
    await page.screenshot({path:info.outputPath(`edited-${width}.png`)})
    await page.goto('/article/42')
    const reader = page.locator('.article-content')
    await expect(reader).toContainText('手动格式示例')
    expect(await formatting(reader)).toEqual(before)
    for (const selector of ['h1','h2']) await expect(reader.locator(selector)).toHaveCSS('text-indent','0px')
    await expect(reader.locator('h2')).toHaveCSS('margin-left','32px')
    await expect(reader.locator('p').filter({hasText:'大号文字'})).toHaveCSS('margin-left','32px')
    for (const text of ['小号文字','大号文字']) await expect(reader.locator('p').filter({hasText:text})).toHaveCSS('text-indent','32px')
    await page.screenshot({path:info.outputPath(`reading-${width}.png`)})
  })
}

test('pasting relative indents normalizes locally and a single undo restores the original document', async ({page}) => {
  const {editor} = await fixture(page)
  await caret(editor.locator('p').filter({hasText:'小号文字'}))
  await editor.evaluate(el => {
    const clipboard = new DataTransfer()
    clipboard.setData('text/html','<p style="text-indent:2em;"><span style="font-size:48px;">粘贴的大号正文</span></p>')
    clipboard.setData('text/plain','粘贴的大号正文')
    el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}))
    el.dispatchEvent(new InputEvent('beforeinput',{inputType:'insertFromPaste',dataTransfer:clipboard,bubbles:true,cancelable:true}))
  })
  const pasted = editor.locator('p').filter({hasText:'粘贴的大号正文'})
  await expect(pasted).toHaveCSS('text-indent','32px')
  await page.keyboard.press('Control+z')
  await expect(editor).not.toContainText('粘贴的大号正文')
  await expect(editor).toContainText('小号文字')
  await expect(editor.locator('h1')).toHaveText('一级标题')
})
