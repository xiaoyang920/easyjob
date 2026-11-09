import { test, expect, type Page, type Locator } from '@playwright/test'

async function open(page: Page, content: string, fullscreen = false) {
  const errors: string[] = []
  page.on('pageerror',error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('userId','7')
    localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Date.now()/1000+3600}))}.indent-delete`)
  })
  await page.route('**/api/**',route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/42/edit')) data = {articleId:'42',title:'缩进删除验收',content,categoryId:'1',status:0,revisionId:'r1',lockVersion:1}
    else if (path.endsWith('/agent/run-overview')) data = {items:[]}
    else if (path.includes('unread-count')) data = 0
    return route.fulfill({json:{code:200,data}})
  })
  await page.goto('/edit-article?id=42')
  await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
  if (fullscreen) await page.locator('.toolbar [data-menu-key="fullScreen"]').click()
  return {editor:page.locator('[data-slate-editor]'),errors}
}
async function select(block: Locator, from = 0, to = from) {
  await block.evaluate((el, {from,to}) => {
    el.closest<HTMLElement>('[data-slate-editor]')!.focus()
    const text = el.querySelector('[data-slate-string]')!.firstChild!
    const range = document.createRange(); range.setStart(text,from); range.setEnd(text,to)
    const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  },{from,to})
}

for (const fullscreen of [false,true]) {
  test(`Backspace consumes one indent stop before merging paragraphs ${fullscreen ? 'in fullscreen' : 'in the page'}`, async ({page}) => {
    const {editor,errors} = await open(page,'<p>上一行</p><p style="text-indent:64px;">当前行</p>',fullscreen)
    const current = editor.locator('p').filter({hasText:'当前行'})
    await select(current)
    await page.keyboard.press('Backspace')
    await expect(current).toHaveCSS('text-indent','32px')
    await expect(editor.locator('p')).toHaveCount(2)
    await expect(current).toHaveText('当前行')
    await page.keyboard.press('Backspace')
    await expect(current).toHaveCSS('text-indent','0px')
    await expect(editor.locator('p')).toHaveCount(2)
    await page.keyboard.press('Control+z')
    await expect(current).toHaveCSS('text-indent','32px')
    await page.keyboard.press('Control+Shift+z')
    await expect(current).toHaveCSS('text-indent','0px')
    await page.keyboard.press('Backspace')
    await expect(editor.locator('p')).toHaveCount(1)
    await expect(editor.locator('p')).toHaveText('上一行当前行')
    expect(errors).toEqual([])
  })
}

test('manually indented headings decrease stepwise without removing their text or heading format',async({page}) => {
  const {editor,errors} = await open(page,'<p>保留上一段</p><h3 style="text-indent:64px;"><strong>用户缩进的标题</strong></h3>')
  const heading = editor.locator('h3')
  await select(heading)
  for (const expected of ['32px','0px']) {
    await page.keyboard.press('Backspace')
    await expect(heading).toHaveCSS('text-indent',expected)
    await expect(heading.locator('strong')).toHaveText('用户缩进的标题')
    await expect(editor.locator('p')).toHaveText('保留上一段')
  }
  expect(errors).toEqual([])
})

test('Backspace inside text or over a text selection deletes text and retains manual indentation',async({page}) => {
  const {editor} = await open(page,'<p>保留上一段</p><p style="text-indent:64px;">第一段文字</p>')
  const paragraph = editor.locator('p').last()
  await select(paragraph,1)
  await page.keyboard.press('Backspace')
  await expect(paragraph).toHaveText('一段文字')
  await expect(paragraph).toHaveCSS('text-indent','64px')
  await select(paragraph,0,2)
  await page.keyboard.press('Backspace')
  await expect(paragraph).toHaveText('文字')
  await expect(paragraph).toHaveCSS('text-indent','64px')
})

test('mobile backward input consumes an indent before invoking native deletion',async({page}) => {
  await page.setViewportSize({width:390,height:844})
  const {editor} = await open(page,'<p>上一行</p><p style="text-indent:64px;">手机输入</p>')
  const paragraph = editor.locator('p').last()
  await select(paragraph)
  const consumed = await editor.evaluate(el => {
    const event = new InputEvent('beforeinput',{inputType:'deleteContentBackward',bubbles:true,cancelable:true})
    el.dispatchEvent(event)
    return event.defaultPrevented
  })
  expect(consumed).toBe(true)
  await expect(paragraph).toHaveCSS('text-indent','32px')
  await expect(paragraph).toHaveText('手机输入')
  await expect(editor.locator('p')).toHaveCount(2)
})

test('all heading levels return to unindented prose on Enter, including manually indented headings',async({page}) => {
  const content = Array.from({length:5},(_,i)=>`<h${i+1} style="text-indent:64px;"><strong>标题${i+1}</strong></h${i+1}>`).join('')
  const {editor} = await open(page,content)
  for (let level=1;level<=5;level++) {
    const heading = editor.locator(`h${level}`)
    await select(heading,3)
    await page.keyboard.press('Enter')
    await page.keyboard.insertText(`正文${level}`)
    const paragraph = editor.locator('p').filter({hasText:`正文${level}`})
    await expect(paragraph).toHaveCSS('text-indent','0px')
    await expect(paragraph.locator('strong')).toHaveCount(0)
    await expect(heading).toHaveCSS('text-indent','64px')
  }
})
