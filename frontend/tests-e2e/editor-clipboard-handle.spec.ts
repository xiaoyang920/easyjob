import { test, expect, type Locator, type Page } from '@playwright/test'

const content = '<h2 style="text-indent:32px;">第一段标题</h2><p style="text-indent:64px;"><span style="font-size:48px;"><strong>缩进文字</strong></span><a href="https://example.org/guide">链接</a></p><p>最后一段</p><p><br></p>'
async function fixture(page: Page, options: { fullscreen?: boolean; dialog?: boolean; content?: string } = {}) {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const html = options.content || content
  await page.addInitScript(() => {
    localStorage.setItem('userId','7')
    localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Date.now()/1000+3600}))}.clipboard-handle`)
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    const pending = {runId:'handle-qa',draftHash:'a'.repeat(64),title:'段落交互测试',draft:html,contentFormat:'html'}
    if (path.endsWith('/article/42/edit')) data = {articleId:'42',title:pending.title,content:html,categoryId:'1',status:0,revisionId:'r1',lockVersion:1}
    else if (path.endsWith('/agent/library')) data = {rows:[{conversationId:'101',title:pending.title}],total:1}
    else if (path.endsWith('/messages')) data = [{role:'assistant',content:html,isDraft:true,interrupted:true,interruptPayload:pending}]
    else if (path.endsWith('/101/run')) data = {runId:pending.runId,status:'awaiting_approval',result:{interrupted:pending}}
    else if (path.endsWith('/agent/run-overview')) data = {items:[]}
    else if (path.includes('unread-count')) data = 0
    return route.fulfill({json:{code:200,data}})
  })
  await page.goto(options.dialog ? '/ai-chat?conversationId=101' : '/edit-article?id=42')
  if (options.dialog) await page.getByRole('button',{name:'直接编辑',exact:true}).click()
  const editor = page.locator('[data-slate-editor]')
  await expect(editor).toContainText('第一段标题')
  if (!options.dialog) await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
  if (options.fullscreen) await page.locator('.toolbar [data-menu-key="fullScreen"]').click()
  return {editor,errors}
}
async function select(block: Locator, from = 0, to?: number) {
  await block.evaluate((el,{from,to}) => {
    el.closest<HTMLElement>('[data-slate-editor]')!.focus()
    const texts = el.querySelectorAll('[data-slate-string]'), first = texts[0]?.firstChild || el.querySelector('[data-slate-zero-width]')!.firstChild!
    const last = to === undefined ? texts[texts.length-1]?.firstChild || first : first
    const range = document.createRange(); range.setStart(first,from); range.setEnd(last,to === undefined ? last.textContent!.length : to)
    const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  },{from,to})
}
async function clipboard(editor: Locator, action = 'copy') {
  return editor.evaluate((el,action) => {
    const data = new DataTransfer()
    el.dispatchEvent(new ClipboardEvent(action,{clipboardData:data,bubbles:true,cancelable:true}))
    return Object.fromEntries(['text/plain','text/html','application/x-slate-fragment'].map(type => [type,data.getData(type)]))
  },action)
}
async function paste(editor: Locator, contents: Record<string,string>) {
  await editor.evaluate((el,contents) => {
    const data = new DataTransfer()
    for (const [type,value] of Object.entries(contents)) data.setData(type,value)
    el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}))
    el.dispatchEvent(new InputEvent('beforeinput',{inputType:'insertFromPaste',dataTransfer:data,bubbles:true,cancelable:true}))
  },contents)
}

test('copy keeps rich paragraph indent, plain text tabs, inline marks and links without changing the source',async({page}) => {
  const {editor,errors} = await fixture(page)
  const paragraph = editor.locator('p').first()
  await select(paragraph)
  const data = await clipboard(editor)
  expect(data['text/plain']).toBe('\t\t缩进文字链接')
  expect(data['text/html']).toMatch(/^<p[^>]*text-indent: 64px/)
  expect(data['text/html']).toMatch(/<strong(?:\s|>)/)
  expect(data['text/html']).toContain('https://example.org/guide')
  expect(data['application/x-slate-fragment']).toBeTruthy()
  await expect(paragraph).toHaveCSS('text-indent','64px')
  await page.keyboard.press('Control+z')
  await expect(paragraph).toHaveText('缩进文字链接')
  // Selecting inside a word must not insert a paragraph indent into plain text.
  await select(paragraph,1,3)
  expect((await clipboard(editor))['text/plain']).toBe('进文')
  expect(errors).toEqual([])
})

test('copying across blocks preserves independent indentation and excludes unselected text',async({page}) => {
  const {editor} = await fixture(page)
  await editor.evaluate(el => {
    ;(el as HTMLElement).focus()
    const heading = el.querySelector('h2 [data-slate-string]')!.firstChild!
    const paragraph = el.querySelector('p a [data-slate-string]')!.firstChild!
    const range = document.createRange(); range.setStart(heading,0); range.setEnd(paragraph,2)
    const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  })
  const data = await clipboard(editor)
  expect(data['text/plain']).toBe('\t第一段标题\n\t\t缩进文字链接')
  expect(data['text/html']).toContain('text-indent: 32px')
  expect(data['text/html']).toContain('text-indent: 64px')
  expect(data['text/html']).not.toContain('最后一段')
})

for (const fullscreen of [false,true]) {
  test(`copy and cut paste into empty blocks keep indent and undo as one edit ${fullscreen?'fullscreen':'page'}`,async({page}) => {
    const {editor,errors} = await fixture(page,{fullscreen})
    const paragraph = editor.locator('p').first()
    await select(paragraph)
    const data = await clipboard(editor)
    await select(editor.locator('p').last(),0,0)
    await paste(editor,data)
    await expect(editor.locator('p').filter({hasText:'缩进文字链接'})).toHaveCount(2)
    const pasted = editor.locator('p').filter({hasText:'缩进文字链接'}).last()
    await expect(pasted).toHaveCSS('text-indent','64px')
    await expect(pasted.locator('strong')).toHaveText('缩进文字')
    await expect(pasted.locator('a')).toHaveAttribute('href','https://example.org/guide')
    await page.keyboard.press('Control+z')
    await expect(editor.locator('p').filter({hasText:'缩进文字链接'})).toHaveCount(1)
    await select(editor.locator('h2'))
    const cut = await clipboard(editor,'cut')
    expect(cut['text/plain']).toBe('\t第一段标题')
    await expect(editor).not.toContainText('第一段标题')
    await select(editor.locator('p').last(),0,0)
    await paste(editor,cut)
    await expect(editor.locator('h2').filter({hasText:'第一段标题'})).toHaveCSS('text-indent','32px')
    expect(errors).toEqual([])
  })
}

test('real browser Ctrl+C puts indentation and selected content on the clipboard',async({page,context}) => {
  await context.grantPermissions(['clipboard-read','clipboard-write'])
  const {editor} = await fixture(page)
  await select(editor.locator('p').first())
  await page.keyboard.press('Control+c')
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('\t\t缩进文字链接')
  await select(editor.locator('p').last(),0,0)
  await page.keyboard.press('Control+v')
  await expect(editor.locator('p').filter({hasText:'缩进文字链接'}).last()).toHaveCSS('text-indent','64px')
})

test('HTML-only paste preserves copied indentation and inline paste respects an existing destination paragraph',async({page}) => {
  const {editor,errors} = await fixture(page)
  await select(editor.locator('p').first())
  const data = await clipboard(editor)
  await select(editor.locator('p').last(),0,0)
  await paste(editor,{'text/html':data['text/html']!,'text/plain':data['text/plain']!})
  const pasted = editor.locator('p').filter({hasText:'缩进文字链接'}).last()
  await expect(pasted).toHaveCSS('text-indent','64px')
  await expect(pasted.locator('strong')).toHaveCSS('font-size','48px')
  await select(editor.locator('p').filter({hasText:'最后一段'}),1,1)
  await paste(editor,data)
  const destination = editor.locator('p').filter({hasText:'最缩进文字链接后一段'})
  await expect(destination).toHaveCSS('text-indent','0px')
  expect(errors).toEqual([])
})

test('copying an indented paragraph with an image retains the image reference on paste',async({page}) => {
  const {editor,errors} = await fixture(page,{content:'<h2>第一段标题</h2><p style="text-indent:32px;">图片前<img src="/images/pelican-bicycle.svg" alt="插图">图片后</p><p><br></p>'})
  await select(editor.locator('p').first())
  const data = await clipboard(editor)
  expect(data['text/plain']).toBe('\t图片前图片后')
  expect(data['text/html']).toContain('/images/pelican-bicycle.svg')
  expect(data['text/html']).not.toContain('data:image')
  await select(editor.locator('p').last(),0,0)
  await paste(editor,data)
  await expect(editor.locator('img[src="/images/pelican-bicycle.svg"]')).toHaveCount(2)
  const pasted = editor.locator('p:has(img)').last()
  await expect(pasted).toHaveCSS('text-indent','32px')
  expect(await pasted.evaluate(el => el.textContent?.replace(/\uFEFF/g,''))).toBe('图片前图片后')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('img[src="/images/pelican-bicycle.svg"]')).toHaveCount(1)
  expect(errors).toEqual([])
})

for (const options of [{},{fullscreen:true},{dialog:true},{dialog:true,fullscreen:true}]) {
  test(`hover handle formats only its block, retains author styles and supports undo ${JSON.stringify(options)}`,async({page},info) => {
    const {editor,errors} = await fixture(page,options)
    const untouched = await editor.locator('h2').innerHTML()
    await editor.locator('h2').click()
    const paragraph = editor.locator('p').first()
    await paragraph.hover()
    const handle = page.getByRole('button',{name:'段落格式：正文',exact:true})
    await expect(handle).toBeVisible()
    const handleBounds = await handle.boundingBox(), blockBounds = await paragraph.boundingBox()
    expect(handleBounds!.x + handleBounds!.width).toBeLessThanOrEqual(blockBounds!.x)
    await handle.click()
    await page.getByRole('menuitemradio',{name:'三级标题'}).click()
    const heading = editor.locator('h3')
    await expect(heading).toHaveText('缩进文字链接')
    await expect(heading).toHaveCSS('text-indent','64px')
    await expect(heading.locator('strong')).toHaveText('缩进文字')
    await expect(heading.locator('a')).toHaveAttribute('href','https://example.org/guide')
    expect(await editor.locator('h2').innerHTML()).toBe(untouched)
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h3')).toHaveCount(0)
    await expect(editor.locator('p').first()).toHaveCSS('text-indent','64px')
    await editor.locator('h2').hover()
    await page.getByRole('button',{name:'段落格式：二级标题',exact:true}).click()
    await page.getByRole('menuitemradio',{name:'正文'}).click()
    await expect(editor.locator('p').filter({hasText:'第一段标题'})).toHaveCSS('text-indent','32px')
    await editor.locator('p').first().hover()
    await page.getByRole('button',{name:'段落格式：正文',exact:true}).click()
    await page.screenshot({path:info.outputPath('block-handle.png')})
    expect(errors).toEqual([])
  })
}

test('handle menu stays in narrow viewports, supports keyboard and Escape keeps fullscreen open',async({page}) => {
  await page.setViewportSize({width:390,height:844})
  const {editor,errors} = await fixture(page,{fullscreen:true})
  await editor.locator('h2').hover()
  const handle = page.getByRole('button',{name:'段落格式：二级标题',exact:true})
  await handle.focus(); await handle.press('Enter')
  const menu = page.getByRole('menu',{name:'切换段落格式'})
  await expect(menu).toBeVisible()
  const rect = await menu.boundingBox()
  expect(rect!.x).toBeGreaterThanOrEqual(0)
  expect(rect!.x+rect!.width).toBeLessThanOrEqual(390)
  await expect(page.getByRole('menuitemradio',{name:'二级标题'})).toBeFocused()
  await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter')
  await expect(editor.locator('h3')).toHaveText('第一段标题')
  await editor.locator('h3').hover()
  const newHandle = page.getByRole('button',{name:'段落格式：三级标题',exact:true})
  await newHandle.focus(); await newHandle.press('Enter')
  await page.keyboard.press('Escape')
  await expect(menu).toHaveCount(0)
  await expect(page.getByRole('dialog',{name:'全屏编辑正文',exact:true})).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog',{name:'全屏编辑正文',exact:true})).toHaveCount(0)
  expect(errors).toEqual([])
})

test('hover excludes structural blocks and clears a stale menu after document changes',async({page}) => {
  const {editor,errors} = await fixture(page,{content:'<h2>第一段标题</h2><p>普通正文</p><pre><code>const a = 1;</code></pre><table><tbody><tr><td>表格文字</td></tr></tbody></table>'})
  await editor.locator('p').first().hover()
  await expect(page.locator('.block-type-handle')).toBeVisible()
  for (const selector of ['pre','td']) {
    await editor.locator(selector).hover()
    await expect(page.locator('.block-type-handle')).toHaveCount(0)
  }
  await editor.locator('h2').hover()
  await page.locator('.block-type-handle').click()
  await editor.locator('p').first().click()
  await expect(page.locator('.block-type-menu')).toHaveCount(0)
  await page.locator('.toolbar [data-menu-key="fullScreen"]').click()
  await expect(page.locator('.block-type-handle')).toHaveCount(0)
  expect(errors).toEqual([])
})

for (const fullscreen of [false, true]) {
  test(`empty lines and an empty document do not show a block handle ${fullscreen ? 'fullscreen' : 'page'}`, async ({ page }) => {
    const { editor, errors } = await fixture(page, { fullscreen })
    const handle = page.locator('.block-type-handle')
    await editor.locator('h2').hover()
    await expect(handle).toBeVisible()
    // The gutter stays traversable, so the nonempty block can still be formatted.
    const bounds = (await handle.boundingBox())!
    await page.mouse.move(bounds.x + bounds.width + 2, bounds.y + bounds.height / 2, { steps: 6 })
    await expect(handle).toBeVisible()
    await handle.click()
    await expect(page.getByRole('menu', { name: '切换段落格式' })).toBeVisible()
    await handle.click()
    await expect(page.getByRole('menu', { name: '切换段落格式' })).toHaveCount(0)
    await editor.locator('p').last().hover()
    await expect(handle).toHaveCount(0)
    await editor.locator('p').first().hover()
    await expect(handle).toBeVisible()
    // Moving down the same canvas must not leave a stale handle next to an old line.
    const body = (await editor.boundingBox())!
    await page.mouse.move(body.x + body.width - 12, body.y + body.height - 8)
    await expect(handle).toHaveCount(0)
    await editor.locator('h2').click()
    await page.keyboard.press('Control+a'); await page.keyboard.press('Backspace')
    await expect(editor).toHaveText('')
    await editor.locator('p').first().hover()
    await expect(handle).toHaveCount(0)
    await page.setViewportSize({ width: 1280, height: 850 })
    await editor.locator('p').first().hover()
    await expect(handle).toHaveCount(0)
    expect(errors).toEqual([])
  })

  test(`deleting the hovered block's content clears its handle without another mouse movement ${fullscreen ? 'fullscreen' : 'page'}`, async ({ page }) => {
    const { editor, errors } = await fixture(page, { fullscreen })
    const paragraph = editor.locator('p').filter({ hasText: '最后一段' })
    await paragraph.click(); await paragraph.hover()
    await expect(page.locator('.block-type-handle')).toBeVisible()
    await page.keyboard.press('Home'); await page.keyboard.press('Shift+End'); await page.keyboard.press('Backspace')
    await expect(editor.locator('p').nth(1)).toHaveText('')
    await expect(page.locator('.block-type-handle')).toHaveCount(0)
    await page.keyboard.press('Control+z')
    await editor.locator('p').filter({ hasText: '最后一段' }).hover()
    await expect(page.locator('.block-type-handle')).toBeVisible()
    expect(errors).toEqual([])
  })
}
