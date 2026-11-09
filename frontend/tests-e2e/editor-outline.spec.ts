import { test, expect, type Locator, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
const feishuClipboard = JSON.parse(readFileSync(new URL('./fixtures/feishu-outline-clipboard.json',import.meta.url),'utf8')) as Record<string,string>

const initial = '<p>父块</p><h2>复制标题</h2><p style="margin-left:32px;"><strong>子段落</strong><a href="https://example.org">链接</a></p><p>同级段落</p><p><br></p>'
async function fixture(page: Page, html = initial, fullscreen = false) {
  const errors: string[] = []
  const writes: any[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('userId','7')
    localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Date.now()/1000+3600}))}.outline`)
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/42') && route.request().method() === 'PUT') {
      const body = route.request().postDataJSON(); writes.push(body); html = body.content
      data = {revisionId:'r2',lockVersion:2,revisionState:0}
    } else if (path.endsWith('/article/42/edit')) data = {articleId:'42',title:'块层级交互',content:html,categoryId:'1',status:0,revisionId:'r1',lockVersion:1}
    else if (path.endsWith('/article/detail/42')) data = {articleId:'42',title:'块层级交互',content:html,canReadFull:true,authorId:'7',authorName:'示例',tags:[]}
    else if (path.endsWith('/agent/run-overview')) data = {items:[]}
    else if (path.includes('unread-count')) data = 0
    else if (path.includes('/comment/')) data = {records:[],total:0,pages:1,nextCursor:''}
    else if (path.startsWith('/api/reading/')) data = {sessionId:'qa',sessionToken:'qa',level:0,totalSeconds:0,rules:[]}
    return route.fulfill({json:{code:200,data}})
  })
  await page.goto('/edit-article?id=42')
  const editor = page.locator('[data-slate-editor]')
  await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
  if (fullscreen) await page.locator('.toolbar [data-menu-key="fullScreen"]').click()
  return {editor,errors,writes}
}
async function select(from: Locator, to = from, end: 'start' | 'end' = 'start') {
  const id = await to.getAttribute('id')
  await from.evaluate((el,{id,end}) => {
    el.closest<HTMLElement>('[data-slate-editor]')!.focus()
    const text = (node: Element, last: boolean) => {
      const leaves = node.querySelectorAll('[data-slate-string],[data-slate-zero-width]')
      return leaves[last ? leaves.length-1 : 0]!.firstChild!
    }
    const target = id ? document.getElementById(id)! : el
    const first = text(el,false), last = text(target,end === 'end')
    const range = document.createRange(); range.setStart(first,0)
    range.setEnd(last,end === 'end' ? last.textContent!.length : 0)
    const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
  },{id,end})
}
async function endCaret(block: Locator) {
  await select(block,block,'end')
  await block.evaluate(() => { const selection = document.getSelection()!; selection.collapseToEnd(); document.dispatchEvent(new Event('selectionchange')) })
}
async function copy(editor: Locator) {
  return editor.evaluate(el => {
    const data = new DataTransfer()
    el.dispatchEvent(new ClipboardEvent('copy',{clipboardData:data,bubbles:true,cancelable:true}))
    return Object.fromEntries(['text/plain','text/html','application/x-slate-fragment'].map(type => [type,data.getData(type)]))
  })
}
async function paste(editor: Locator, data: Record<string,string>) {
  await editor.evaluate((el,contents) => {
    const data = new DataTransfer()
    for (const [type,value] of Object.entries(contents)) data.setData(type,value)
    el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}))
    el.dispatchEvent(new InputEvent('beforeinput',{inputType:'insertFromPaste',dataTransfer:data,bubbles:true,cancelable:true}))
  },data)
}
async function textLeft(block: Locator) {
  return block.evaluate(el => {
    const selector = '[data-slate-string],[data-slate-zero-width]'
    const leaf = (el.matches(selector) ? el : el.querySelector(selector))?.firstChild
      || document.createTreeWalker(el,NodeFilter.SHOW_TEXT).nextNode()!
    const range = document.createRange()
    range.setStart(leaf,0); range.setEnd(leaf,Math.min(1,leaf.textContent!.length))
    return range.getBoundingClientRect().left
  })
}

for (const rich of ['native','html']) for (const tabs of [1,2]) {
  test(`${rich} paste after ${tabs} Tab rebases the forest and keeps internal depth`,async({page},info) => {
    if (rich === 'html' && tabs === 2) await page.setViewportSize({width:390,height:844})
    const {editor,errors} = await fixture(page,initial,tabs === 2)
    await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','32px')
    await select(editor.locator('h2'),editor.locator('p').filter({hasText:'同级段落'}),'end')
    const data = await copy(editor)
    expect(data['text/plain']).toBe('复制标题\n\t子段落链接\n同级段落')
    if (rich === 'html') delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for (let i = 0; i < tabs; i++) await page.keyboard.press('Tab')
    await paste(editor,data)
    const depth = (tabs-1)*32
    await expect(editor.locator('h2')).toHaveCount(2)
    await expect(editor.locator('h2').last()).toHaveCSS('margin-left',`${depth}px`)
    await expect(editor.locator('h2').last()).toHaveCSS('text-indent','0px')
    const child = editor.locator('p').filter({hasText:'子段落'}).last()
    await expect(child).toHaveCSS('margin-left',`${depth+32}px`)
    await expect(child).toHaveCSS('text-indent','0px')
    await expect(child.locator('strong')).toHaveText('子段落')
    await expect(child.locator('a')).toHaveAttribute('href','https://example.org')
    await expect(editor.locator('p').filter({hasText:'同级段落'}).last()).toHaveCSS('margin-left',`${depth}px`)
    await page.screenshot({path:info.outputPath('outline-paste.png')})
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h2')).toHaveCount(1)
    await expect(editor.locator('p').last()).toHaveCSS('text-indent','32px')
    await expect(editor.locator('p').last()).toHaveCSS('margin-left',`${depth}px`)
    expect(errors).toEqual([])
  })
}

test('Tab is independent of preceding depth; Backspace removes first-line then block depth before merging',async({page}) => {
  const {editor,errors} = await fixture(page,'<p>父块</p><p><span style="font-size:48px;">大字</span></p><p>末尾</p>')
  const block = editor.locator('p').filter({hasText:'大字'})
  await select(block)
  await page.keyboard.press('Tab')
  await expect(block).toHaveCSS('text-indent','32px')
  await expect(block).toHaveCSS('margin-left','0px')
  await page.keyboard.press('Tab')
  await expect(block).toHaveCSS('margin-left','32px')
  await page.keyboard.press('Tab')
  await expect(page.getByText('当前内容块已达最大缩进层级',{exact:true})).toHaveCount(0)
  await expect(block).toHaveCSS('margin-left','64px')
  await page.keyboard.press('Backspace')
  await expect(block).toHaveCSS('text-indent','0px')
  await expect(block).toHaveCSS('margin-left','64px')
  await page.keyboard.press('Backspace')
  await expect(block).toHaveCSS('margin-left','32px')
  await page.keyboard.press('Backspace')
  await expect(block).toHaveCSS('margin-left','0px')
  await expect(editor.locator('p')).toHaveCount(3)
  await page.keyboard.press('Backspace')
  await expect(editor.locator('p')).toHaveCount(2)
  await expect(editor.locator('p').first()).toHaveText('父块大字')
  expect(errors).toEqual([])
})

test('selected parent and child each move once and undo restores the selected blocks',async({page}) => {
  const {editor,errors} = await fixture(page)
  await select(editor.locator('h2'),editor.locator('p').filter({hasText:'子段落'}),'end')
  await page.keyboard.press('Tab')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','32px')
  await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','64px')
  await expect(editor.locator('p').filter({hasText:'同级段落'})).toHaveCSS('margin-left','0px')
  await page.keyboard.press('Control+z')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','0px')
  await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','32px')
  await page.keyboard.press('Control+Shift+z')
  await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','64px')
  await page.keyboard.press('Shift+Tab')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','0px')
  await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','32px')
  expect(errors).toEqual([])
})

test('heading Enter keeps structural alignment without adding automatic first-line indentation',async({page}) => {
  const {editor,errors} = await fixture(page,'<p>父块</p><h2 style="margin-left:32px;">复制标题</h2><p style="margin-left:64px;">子段落链接</p><p>同级段落</p>')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','32px')
  await endCaret(editor.locator('h2'))
  await page.keyboard.press('Enter')
  await page.keyboard.type('新正文')
  const paragraph = editor.locator('p').filter({hasText:'新正文'})
  await expect(paragraph).toHaveCSS('margin-left','32px')
  await expect(paragraph).toHaveCSS('text-indent','0px')
  // Enter inserts at the caret, before the following indented paragraphs.
  const order = await editor.locator(':scope > [data-slate-node="element"]').allTextContents()
  expect(order).toEqual(['父块','复制标题','新正文','子段落链接','同级段落'])
  await select(editor.locator('h2')); await page.keyboard.press('Enter')
  await expect(editor.locator('h2')).toHaveText('复制标题')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','32px')
  expect(errors).toEqual([])
})

test('headings indent independently until the storage depth limit',async({page}) => {
  const {editor,errors} = await fixture(page,'<p>父块</p><p style="margin-left:32px;">前行</p><h3>后行</h3>')
  await expect(editor.locator('p').first()).toHaveCSS('margin-left','0px')
  await expect(editor.locator('p').nth(1)).toHaveCSS('margin-left','32px')
  const heading = editor.locator('h3')
  await select(heading)
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab')
  await expect(heading).toHaveCSS('margin-left','64px')
  await page.keyboard.press('Tab')
  await expect(heading).toHaveCSS('margin-left','96px')
  await expect(page.getByText('当前内容块已达最大缩进层级',{exact:true})).toHaveCount(0)
  for(let i=3;i<8;i++) await page.keyboard.press('Tab')
  await expect(heading).toHaveCSS('margin-left','256px')
  await page.keyboard.press('Tab')
  await expect(heading).toHaveCSS('margin-left','256px')
  await expect(page.getByText('当前内容块已达最大缩进层级',{exact:true})).toBeVisible()
  await expect(editor.locator('p').nth(1)).toHaveCSS('margin-left','32px')
  await page.keyboard.press('Shift+Tab')
  await expect(heading).toHaveCSS('margin-left','224px')
  expect(errors).toEqual([])
})

test('a selection ending at the next root start does not indent that unselected root',async({page}) => {
  const {editor,errors} = await fixture(page,'<p>父块</p><p>选中的行</p><p>未选中的行</p>')
  await select(editor.locator('p').nth(1),editor.locator('p').nth(2))
  await page.keyboard.press('Tab')
  await expect(editor.locator('p').nth(1)).toHaveCSS('margin-left','32px')
  await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left','0px')
  expect(errors).toEqual([])
})

test('copying a nested subtree uses relative depths and inline paste retains the destination format',async({page}) => {
  const html = '<p>父块</p><h2 style="margin-left:32px;">嵌套标题</h2><p style="margin-left:64px;">嵌套子块</p><p style="margin-left:32px;">尾行</p><p><br></p>'
  const {editor,errors} = await fixture(page,html)
  await select(editor.locator('h2'),editor.locator('p').filter({hasText:'嵌套子块'}),'end')
  const tree = await copy(editor)
  await select(editor.locator('p').last()); await page.keyboard.press('Tab'); await page.keyboard.press('Tab')
  await paste(editor,tree)
  await expect(editor.locator('h2').last()).toHaveCSS('margin-left','32px')
  await expect(editor.locator('p').filter({hasText:'嵌套子块'}).last()).toHaveCSS('margin-left','64px')
  await select(editor.locator('p').filter({hasText:'嵌套子块'}).first(),editor.locator('p').filter({hasText:'嵌套子块'}).first(),'end')
  const inline = await copy(editor)
  const target = editor.locator('p').filter({hasText:'尾行'})
  await endCaret(target); await paste(editor,inline)
  await expect(target).toHaveText('尾行嵌套子块')
  await expect(target).toHaveCSS('margin-left','32px')
  await expect(target).toHaveCSS('text-indent','0px')
  expect(errors).toEqual([])
})

for (const native of [true,false]) for (const tabs of [0,1,2,3]) {
  test(`${native?'native':'HTML'} source offsets are preserved unless explicitly nesting an empty target (${tabs} Tab)`,async({page}) => {
    const html = '<p>父块</p><h2 style="margin-left:64px;">缩进标题</h2><p style="margin-left:96px;">缩进子块</p><p style="margin-left:64px;">目标前一块</p><p><br></p>'
    const {editor,errors} = await fixture(page,html)
    await select(editor.locator('h2'),editor.locator('p').filter({hasText:'缩进子块'}),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for (let i = 0; i < tabs; i++) await page.keyboard.press('Tab')
    await paste(editor,data)
    const depth = tabs < 2 ? 64 : 32
    await expect(editor.locator('h2').last()).toHaveCSS('margin-left',`${depth}px`)
    await expect(editor.locator('p').filter({hasText:'缩进子块'}).last()).toHaveCSS('margin-left',`${depth+32}px`)
    await expect(editor.locator('h2').last()).toHaveCSS('text-indent','0px')
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h2')).toHaveCount(1)
    if (tabs === 2) {
      await page.keyboard.press('Control+Shift+z')
      await expect(editor.locator('h2')).toHaveCount(2)
      await expect(editor.locator('h2').last()).toHaveCSS('margin-left','32px')
      await page.keyboard.press('Control+z')
      await paste(editor,data)
      await expect(editor.locator('h2').last()).toHaveCSS('margin-left','32px')
    }
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) for (const key of ['Backspace','Shift+Tab']) {
  test(`outdenting a restored paste target cancels its old anchor (${native?'native':'HTML'}, ${key})`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p style="margin-left:96px;">来源首行</p><p style="margin-left:128px;">来源子行</p><p><br></p>')
    await select(editor.locator('p').first(),editor.locator('p').nth(1),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for(let i=0;i<3;i++) await page.keyboard.press('Tab')
    await paste(editor,data)
    await expect(editor.getByText('来源首行',{exact:true})).toHaveCount(2)
    await page.keyboard.press('Control+z')
    await expect(editor.locator('p')).toHaveCount(3)
    const target = editor.locator('p').last()
    await expect(target).toHaveCSS('margin-left','64px')
    await expect(target).toHaveCSS('text-indent','32px')
    await page.keyboard.press(key)
    await expect(target).toHaveCSS('text-indent','0px')
    await expect(target).toHaveCSS('margin-left','64px')
    await paste(editor,data)
    await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left','96px')
    await expect(editor.locator('p').nth(3)).toHaveCSS('margin-left','128px')
    expect(errors).toEqual([])
  })

  test(`deleting pasted content and all indentation leaves no sticky paste anchor (${native?'native':'HTML'}, ${key})`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p>来源首行</p><p style="margin-left:32px;">来源子行</p><p><br></p>')
    await select(editor.locator('p').first(),editor.locator('p').nth(1),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for(let i=0;i<3;i++) await page.keyboard.press('Tab')
    await paste(editor,data)
    await select(editor.locator('p').nth(2),editor.locator('p').nth(3),'end')
    await page.keyboard.press('Backspace')
    const target = editor.locator('p').last()
    await expect(editor.locator('p')).toHaveCount(3)
    // Native range deletion can retain the last selected block's formatting.
    // Remove every visible stop, stopping before Backspace would merge blocks.
    for(let i=0;i<9;i++) {
      const indented = await target.evaluate(el => {
        const style = getComputedStyle(el)
        return parseFloat(style.marginLeft)>0 || parseFloat(style.textIndent)>0
      })
      if (!indented) break
      await page.keyboard.press(key)
    }
    await expect(target).toHaveCSS('margin-left','0px')
    await expect(target).toHaveCSS('text-indent','0px')
    await paste(editor,data)
    await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left','0px')
    await expect(editor.locator('p').nth(3)).toHaveCSS('margin-left','32px')
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) {
  test(`fresh Tabs after outdenting establish a new anchor (${native?'native':'HTML'})`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p style="margin-left:192px;">来源首行</p><p style="margin-left:224px;">来源子行</p><p><br></p>')
    await select(editor.locator('p').first(),editor.locator('p').nth(1),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for(let i=0;i<3;i++) await page.keyboard.press('Tab')
    await paste(editor,data); await page.keyboard.press('Control+z')
    await expect(editor.locator('p')).toHaveCount(3)
    await page.keyboard.press('Shift+Tab')
    await page.keyboard.press('Tab')
    await paste(editor,data)
    await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left','192px')
    await page.keyboard.press('Control+z')
    await expect(editor.locator('p')).toHaveCount(3)
    await page.keyboard.press('Tab')
    await paste(editor,data)
    await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left','96px')
    await expect(editor.locator('p').nth(3)).toHaveCSS('margin-left','128px')
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) for (const redo of [false,true]) {
  test(`undo and redo restore the current paste-anchor eligibility (${native?'native':'HTML'}, redo=${redo})`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p style="margin-left:96px;">来源首行</p><p style="margin-left:128px;">来源子行</p><p><br></p>')
    await select(editor.locator('p').first(),editor.locator('p').nth(1),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for(let i=0;i<3;i++) await page.keyboard.press('Tab')
    await page.keyboard.press('Shift+Tab')
    await page.keyboard.press('Control+z')
    await expect(editor.locator('p').last()).toHaveCSS('text-indent','32px')
    if (redo) {
      await page.keyboard.press('Control+Shift+z')
      await expect(editor.locator('p').last()).toHaveCSS('text-indent','0px')
    }
    await paste(editor,data)
    const base = redo ? 96 : 32
    await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left',`${base}px`)
    await expect(editor.locator('p').nth(3)).toHaveCSS('margin-left',`${base+32}px`)
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) {
  test(`a cancelled anchor cannot revive when later content has matching indentation (${native?'native':'HTML'})`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p style="margin-left:64px;text-indent:32px;">来源文字</p><p><br></p>')
    await select(editor.locator('p').first(),editor.locator('p').first(),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await select(editor.locator('p').last())
    for(let i=0;i<3;i++) await page.keyboard.press('Tab')
    await paste(editor,data); await page.keyboard.press('Control+z')
    await expect(editor.getByText('来源文字',{exact:true})).toHaveCount(1)
    await page.keyboard.press('Shift+Tab')
    await paste(editor,data)
    await expect(editor.locator('p').last()).toHaveCSS('margin-left','64px')
    await expect(editor.locator('p').last()).toHaveCSS('text-indent','32px')
    await select(editor.locator('p').last(),editor.locator('p').last(),'end')
    await page.keyboard.press('Backspace')
    await paste(editor,data)
    await expect(editor.locator('p').last()).toHaveCSS('margin-left','64px')
    await expect(editor.locator('p').last()).toHaveCSS('text-indent','32px')
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) for (const firstLine of [16,64]) {
  test(`legacy ${firstLine}px source first-line indent keeps visible offsets at the prepared target (${native?'native':'HTML'})`,async({page}) => {
    const {editor,errors} = await fixture(page,`<p style="text-indent:${firstLine}px;">来源第一行</p><p style="margin-left:32px;text-indent:${firstLine}px;">来源第二行</p><p style="text-indent:${firstLine}px;">来源第三行</p><p style="text-indent:${firstLine===16?16:0}px;"><br></p>`)
    await select(editor.locator('p').first(),editor.locator('p').nth(2),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    const target = editor.locator('p').last()
    await select(target); await page.keyboard.press('Tab')
    const anchor = await textLeft(target)
    await page.keyboard.press('Tab'); await paste(editor,data)
    for(const [text,offset] of [['来源第一行',0],['来源第二行',32],['来源第三行',0]] as const) {
      expect(await textLeft(editor.getByText(text,{exact:true}).last())).toBeCloseTo(anchor+offset,1)
    }
    expect(errors).toEqual([])
  })
}

test('keyboard-authored three-line source pastes at the first Tab position after Enter',async({page},info) => {
  const {editor,errors,writes} = await fixture(page,'<p><br></p>')
  await select(editor.locator('p'))
  await page.keyboard.press('Tab'); await page.keyboard.insertText('12312')
  await page.keyboard.press('Enter'); await page.keyboard.press('Tab'); await page.keyboard.insertText('23123')
  await page.keyboard.press('Enter'); await page.keyboard.press('Shift+Tab'); await page.keyboard.insertText('3213')
  const original = await Promise.all([0,1,2].map(index=>textLeft(editor.locator('p').nth(index))))
  expect(original[1]!-original[0]!).toBeCloseTo(32,1)
  expect(original[2]).toBeCloseTo(original[0]!,1)
  await select(editor.locator('p').first(),editor.locator('p').last(),'end')
  const data = await copy(editor)
  await endCaret(editor.locator('p').last()); await page.keyboard.press('Enter')
  await page.keyboard.press('Tab')
  const anchor = await textLeft(editor.locator('p').last())
  await page.keyboard.press('Tab'); await paste(editor,data)
  const check = async(root:Locator) => {
    // Reading and editing pages have different canvas positions. Compare
    // author offsets relative to the unchanged source on the same page.
    const expectedAnchor = await textLeft(root.getByText('12312',{exact:true}).first())+anchor-original[0]!
    for (const [text,offset] of [['12312',0],['23123',32],['3213',0]] as const) {
      expect(await textLeft(root.getByText(text,{exact:true}).last())).toBeCloseTo(expectedAnchor+offset,1)
    }
  }
  await check(editor)
  await page.keyboard.press('Control+s'); await expect.poll(()=>writes.length).toBeGreaterThan(0)
  await page.reload(); await check(editor)
  await page.screenshot({path:info.outputPath('first-tab-visible-anchor.png')})
  await page.goto('/article/42'); await check(page.locator('.article-content'))
  expect(errors).toEqual([])
})

for (const options of [{fullscreen:false,width:1440},{fullscreen:true,width:1440},{fullscreen:true,width:390}]) {
  test(`Enter at the third visible line inserts exactly one adjacent paragraph ${JSON.stringify(options)}`,async({page}) => {
    await page.setViewportSize({width:options.width,height:1000})
    const html = '<h1>一级标题</h1><h2 style="margin-left:32px;">二级标题</h2><p style="margin-left:64px;">第三行正文</p><p style="margin-left:96px;">下一行正文</p><p style="margin-left:128px;">再下一行正文</p><p style="margin-left:64px;">末尾正文</p>'
    const {editor,errors} = await fixture(page,html,options.fullscreen)
    await endCaret(editor.locator('p').filter({hasText:'第三行正文'}))
    await page.keyboard.press('Enter')
    await expect(editor.locator(':scope > [data-slate-node="element"]')).toHaveCount(7)
    await page.keyboard.insertText('在这里继续写')
    await expect(editor.locator(':scope > [data-slate-node="element"]')).toHaveText(['一级标题','二级标题','第三行正文','在这里继续写','下一行正文','再下一行正文','末尾正文'])
    await expect(editor.locator('p').filter({hasText:'在这里继续写'})).toHaveCSS('margin-left','64px')
    await expect(editor.locator('p').filter({hasText:/^下一行正文$/})).toHaveCSS('margin-left','96px')
    await expect(editor.locator('p').filter({hasText:'再下一行正文'})).toHaveCSS('margin-left','128px')
    expect(errors).toEqual([])
  })

  test(`consecutive Enter presses add one paragraph per press at the caret ${JSON.stringify(options)}`,async({page}) => {
    await page.setViewportSize({width:options.width,height:1000})
    const {editor,errors} = await fixture(page,'<p style="margin-left:32px;">正在写的正文</p><p style="margin-left:64px;">后面的缩进正文</p><p>结尾</p>',options.fullscreen)
    await endCaret(editor.locator('p').first())
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await page.keyboard.insertText('第二次回车后')
    await expect(editor.locator(':scope > [data-slate-node="element"]')).toHaveText(['正在写的正文','','第二次回车后','后面的缩进正文','结尾'])
    await expect(editor.locator('p').nth(1)).toHaveCSS('margin-left','32px')
    await expect(editor.locator('p').nth(2)).toHaveCSS('margin-left','32px')
    expect(errors).toEqual([])
  })
}

for (const tag of ['p','h2']) {
  test(`Enter undo and redo keep the caret immediately after the original ${tag}`,async({page}) => {
    const {editor,errors} = await fixture(page,`<${tag} style="margin-left:32px;">当前位置</${tag}><p style="margin-left:64px;">下面的正文</p><p>最后一行</p>`)
    const blocks = editor.locator(':scope > [data-slate-node="element"]')
    await endCaret(editor.locator(tag).first())
    await page.keyboard.press('Enter')
    await expect(blocks).toHaveText(['当前位置','','下面的正文','最后一行'])
    await page.keyboard.press('Control+z')
    await expect(blocks).toHaveText(['当前位置','下面的正文','最后一行'])
    await page.keyboard.press('Control+Shift+z')
    await expect(blocks).toHaveText(['当前位置','','下面的正文','最后一行'])
    await page.keyboard.insertText('接着写')
    await expect(blocks).toHaveText(['当前位置','接着写','下面的正文','最后一行'])
    expect(errors).toEqual([])
  })
}

test('Enter-inherited depth does not silently opt into relative paste; leading offsets survive reload',async({page}) => {
  const html = '<h2 style="margin-left:64px;">原缩进标题</h2><p style="margin-left:96px;">另一层级</p>'
  const {editor,errors,writes} = await fixture(page,html)
  await select(editor.locator('h2'),editor.locator('h2'),'end')
  const data = await copy(editor)
  await endCaret(editor.locator('p')); await page.keyboard.press('Enter')
  await expect(editor.locator('p').last()).toHaveCSS('margin-left','96px')
  await paste(editor,data)
  await expect(editor.locator('h2').last()).toHaveCSS('margin-left','64px')
  await page.keyboard.press('Control+s')
  await expect.poll(()=>writes.length).toBeGreaterThan(0)
  await page.reload()
  await expect(editor.locator('h2').first()).toHaveCSS('margin-left','64px')
  await expect(editor.locator('h2').last()).toHaveCSS('margin-left','64px')
  expect(errors).toEqual([])
})

for (const fallback of ['record','embedded','html']) {
  test(`real Feishu clipboard ${fallback} keeps source formatting through paste, save and reading`,async({page},info) => {
    const {editor,errors,writes} = await fixture(page,'<p>父块</p><p><br></p>')
    const data = {...feishuClipboard}
    if (fallback !== 'record') {
      delete data['docx/record']
      if (fallback === 'embedded') {
        const escaped = feishuClipboard['docx/record']!.replaceAll('&','&amp;').replaceAll('"','&quot;')
        data['text/html'] += `<span data-lark-record-data="${escaped}" class="lark-record-clipboard"></span>`
      }
    }
    await select(editor.locator('p').last()); await paste(editor,data)
    const check = async (root: Locator) => {
      await expect(root.locator('h1')).toHaveCount(2)
      await expect(root.locator('h1').first()).toHaveCSS('margin-left','0px')
      await expect(root.locator('h1').last()).toHaveCSS('margin-left','32px')
      await expect(root.locator('h1').first()).toHaveCSS('font-size','28.8px')
      await expect(root.locator('p').filter({hasText:'第一行正文'})).toHaveCount(2)
      const nested = root.locator('p').filter({hasText:'第一行正文'}).last()
      await expect(nested).toHaveCSS('margin-left','32px')
      await expect(nested).toHaveCSS('line-height','26px')
      await expect(nested).toHaveText('第一行正文')
    }
    await check(editor)
    await page.keyboard.press('Control+s'); await expect.poll(()=>writes.length).toBeGreaterThan(0)
    expect(writes.at(-1).content).not.toMatch(/data-lark|recordMap|old-record-id/)
    await page.reload(); await check(editor)
    await page.goto('/article/42'); await check(page.locator('.article-content'))
    await page.screenshot({path:info.outputPath('feishu-import-reading.png')})
    expect(errors).toEqual([])
  })
}

for (const tabs of [2,3]) {
  test(`Feishu source uses the explicitly prepared target base after ${tabs} Tab`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p>父块</p><p style="margin-left:32px;">前一子块</p><p><br></p>',true)
    await select(editor.locator('p').last())
    for (let i=0;i<tabs;i++) await page.keyboard.press('Tab')
    await paste(editor,feishuClipboard)
    await expect(editor.locator('h1').first()).toHaveCSS('margin-left','32px')
    await expect(editor.locator('h1').last()).toHaveCSS('margin-left','64px')
    expect(errors).toEqual([])
  })
}

test('Feishu rich formatting, native structures and image references survive actual editor import',async({page},info) => {
  const {editor,errors,writes} = await fixture(page,'<p>父块</p><p><br></p>')
  await select(editor.locator('p').last())
  await paste(editor,{'text/plain':'格式正文','text/html':'<div data-lark-html-role="root"><h2 class="ace-line" style="text-align:center"><span style="font-size:26px;color:rgb(30,60,90);background-color:#ffeeaa;font-weight:700;font-style:italic;text-decoration:underline line-through">格式正文</span><a href="https://example.org/guide">链接</a></h2><div class="ace-line text-indent" style="text-indent:2em">正文<img src="/images/pelican-bicycle.svg" alt="插图"></div><ol><li>有序列表</li></ol><ul><li>无序列表</li></ul><table><tbody><tr><td><strong>表格文字</strong></td></tr></tbody></table><pre><code class="language-java">  int a = 1;</code></pre></div>'})
  const check = async(root: Locator) => {
    const heading = root.locator('h2')
    await expect(heading).toHaveCSS('text-align','center')
    const text = heading.locator('s').filter({hasText:'格式正文'})
    await expect(text).toHaveCSS('font-size','26px')
    await expect(text).toHaveCSS('color','rgb(30, 60, 90)')
    await expect(heading.locator('strong')).toContainText('格式正文')
    await expect(heading.locator('em')).toContainText('格式正文')
    await expect(heading.locator('u')).toContainText('格式正文')
    await expect(heading.locator('a')).toHaveAttribute('href','https://example.org/guide')
    await expect(root.locator('p').filter({hasText:'正文'})).toHaveCSS('text-indent','32px')
    await expect(root.locator('img[src="/images/pelican-bicycle.svg"]')).toHaveCount(1)
    if (await root.getAttribute('data-slate-editor') !== null) {
      // wangEditor renders editable list items as divs with visible markers.
      const numbered = await root.getByText('有序列表',{exact:true}).evaluate(el=>el.closest('[data-slate-node="element"]')!.textContent)
      const bulleted = await root.getByText('无序列表',{exact:true}).evaluate(el=>el.closest('[data-slate-node="element"]')!.textContent)
      expect(numbered).toMatch(/1\.\s*有序列表/)
      expect(bulleted).toMatch(/•\s*无序列表/)
    } else {
      await expect(root.locator('ol')).toContainText('有序列表')
      await expect(root.locator('ul')).toContainText('无序列表')
    }
    await expect(root.locator('td')).toContainText('表格文字')
    await expect(root.locator('pre code')).toContainText('int a = 1;')
  }
  await check(editor)
  await page.keyboard.press('Control+s'); await expect.poll(()=>writes.length).toBeGreaterThan(0)
  await page.reload(); await check(editor)
  await page.goto('/article/42'); await check(page.locator('.article-content'))
  await page.screenshot({path:info.outputPath('feishu-rich-import.png')})
  expect(errors).toEqual([])
})

for (const options of [{fullscreen:false,width:1440},{fullscreen:true,width:1440},{fullscreen:true,width:390}]) {
  test(`Tab changes only selected blocks and leaves unselected descendants fixed ${JSON.stringify(options)}`,async({page},info) => {
    await page.setViewportSize({width:options.width,height:1000})
    const html = '<p>父块</p><h2>选择标题</h2><p style="margin-left:32px;">选择正文</p><p style="margin-left:64px;">后面的未选中内容</p><p style="margin-left:32px;">另一未选中行</p><p>结尾</p>'
    const {editor,errors} = await fixture(page,html,options.fullscreen)
    const unselected = editor.locator('p').filter({hasText:'后面的未选中内容'})
    const another = editor.locator('p').filter({hasText:'另一未选中行'})
    const before = [await unselected.getAttribute('style'),await another.getAttribute('style')]
    const check = async() => {
      expect([await unselected.getAttribute('style'),await another.getAttribute('style')]).toEqual(before)
      await expect(editor.locator('p').filter({hasText:'结尾'})).toHaveCSS('margin-left','0px')
    }
    await select(editor.locator('h2'),editor.locator('p').filter({hasText:'选择正文'}),'end')
    await page.keyboard.press('Tab')
    await expect(editor.locator('h2')).toHaveCSS('margin-left','32px')
    await expect(editor.locator('p').filter({hasText:'选择正文'})).toHaveCSS('margin-left','64px')
    await check()
    await page.keyboard.press('Shift+Tab')
    await expect(editor.locator('h2')).toHaveCSS('margin-left','0px')
    await expect(editor.locator('p').filter({hasText:'选择正文'})).toHaveCSS('margin-left','32px')
    await check()
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h2')).toHaveCSS('margin-left','32px'); await check()
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h2')).toHaveCSS('margin-left','0px'); await check()
    await page.screenshot({path:info.outputPath('selection-only-tab.png')})
    expect(errors).toEqual([])
  })
}

test('a caret Tab on a heading does not move following child blocks',async({page}) => {
  const {editor} = await fixture(page)
  await select(editor.locator('h2')); await page.keyboard.press('Tab')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','32px')
  await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','32px')
  await page.keyboard.press('Shift+Tab')
  await expect(editor.locator('h2')).toHaveCSS('margin-left','0px')
  await expect(editor.locator('p').filter({hasText:'子段落'})).toHaveCSS('margin-left','32px')
})

for (const tabs of [2,3]) {
  test(`the first Tab base includes the original target offset and stays fixed after ${tabs} Tab`,async({page}) => {
    const {editor} = await fixture(page,'<p style="margin-left:128px;">前行</p><p style="margin-left:32px;"><br></p>')
    await select(editor.locator('p').last())
    await page.keyboard.press('Tab')
    await expect(editor.locator('p').last()).toHaveCSS('margin-left','32px')
    await expect(editor.locator('p').last()).toHaveCSS('text-indent','32px')
    for(let index=1;index<tabs;index++) await page.keyboard.press('Tab')
    await paste(editor,feishuClipboard)
    await expect(editor.locator('h1').first()).toHaveCSS('margin-left','64px')
    await expect(editor.locator('h1').last()).toHaveCSS('margin-left','96px')
  })
}

test('clearing an old imported heading size restores website defaults and supports undo',async({page}) => {
  const {editor,errors,writes} = await fixture(page,'<p>前文</p><h1 style="font-size:26px;line-height:1.4;"><span style="font-size:26px;">旧导入标题</span></h1><p>后文</p>')
  const heading = editor.locator('h1')
  await expect(heading).toHaveCSS('font-size','26px')
  await select(heading,heading,'end')
  const clear = page.locator('.w-e-hover-bar [data-menu-key="clearStyle"]')
  await expect(clear).toBeVisible(); await clear.click()
  await expect(heading).toHaveCSS('font-size','28.8px')
  await expect(heading.locator('[data-slate-string]')).toHaveCSS('font-size','28.8px')
  await expect(editor.locator('p')).toHaveText(['前文','后文'])
  await page.keyboard.press('Control+z')
  await expect(heading).toHaveCSS('font-size','26px')
  await select(heading,heading,'end'); await expect(clear).toBeVisible(); await clear.click()
  await page.keyboard.press('Control+s'); await expect.poll(()=>writes.length).toBeGreaterThan(0)
  await page.reload(); await expect(heading).toHaveCSS('font-size','28.8px')
  await page.goto('/article/42'); await expect(page.locator('.article-content h1')).toHaveCSS('font-size','28.8px')
  expect(errors).toEqual([])
})

for (const native of [true,false]) for (const tabs of [2,3]) {
  test(`an empty first block accepts ${tabs} Tab and ${native?'native':'HTML'} paste uses its first Tab position`,async({page}) => {
    const {editor,errors} = await fixture(page,'<p><br></p><h2 style="margin-left:64px;">来源标题</h2><p style="margin-left:96px;">来源正文</p>')
    await select(editor.locator('h2'),editor.locator('p').filter({hasText:'来源正文'}),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    const target = editor.locator('p').first()
    await select(target)
    for(let i=0;i<tabs;i++) await page.keyboard.press('Tab')
    await expect(target).toHaveCSS('margin-left',`${(tabs-1)*32}px`)
    await expect(target).toHaveCSS('text-indent','32px')
    await expect(page.getByText('当前内容块已达最大缩进层级',{exact:true})).toHaveCount(0)
    await paste(editor,data)
    await expect(editor.locator('h2').first()).toHaveCSS('margin-left','32px')
    await expect(editor.locator('p').filter({hasText:'来源正文'}).first()).toHaveCSS('margin-left','64px')
    await expect(editor.locator('h2').last()).toHaveCSS('margin-left','64px')
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h2')).toHaveCount(1)
    await expect(editor.locator('p').first()).toHaveCSS('margin-left',`${(tabs-1)*32}px`)
    await paste(editor,data)
    await expect(editor.locator('h2').first()).toHaveCSS('margin-left','32px')
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) for (const tabs of [1,2,3]) {
  test(`an Enter-inherited first-line indent counts explicit Tab presses for ${native?'native':'HTML'} paste (${tabs} Tab)`,async({page},info) => {
    const {editor,errors} = await fixture(page,'<h2 style="margin-left:64px;">来源标题</h2><p style="margin-left:96px;">来源正文</p><p style="margin-left:96px;text-indent:32px;">接着写</p>',tabs===3)
    await select(editor.locator('h2'),editor.locator('p').filter({hasText:'来源正文'}),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    await endCaret(editor.locator('p').last()); await page.keyboard.press('Enter')
    const target = editor.locator('p').last()
    await expect(target).toHaveCSS('margin-left','96px')
    await expect(target).toHaveCSS('text-indent','32px')
    for(let i=0;i<tabs;i++) await page.keyboard.press('Tab')
    await expect(target).toHaveCSS('margin-left',`${(3+tabs)*32}px`)
    await expect(page.getByText('当前内容块已达最大缩进层级',{exact:true})).toHaveCount(0)
    await paste(editor,data)
    const base = tabs===1 ? 64 : 160
    await expect(editor.locator('h2').last()).toHaveCSS('margin-left',`${base}px`)
    await expect(editor.locator('p').filter({hasText:'来源正文'}).last()).toHaveCSS('margin-left',`${base+32}px`)
    await expect(editor.locator('p').filter({hasText:'接着写'})).toHaveCSS('margin-left','96px')
    await page.keyboard.press('Control+z')
    await expect(editor.locator('h2')).toHaveCount(1)
    await expect(editor.locator('p').last()).toHaveCSS('margin-left',`${(3+tabs)*32}px`)
    await paste(editor,data)
    await expect(editor.locator('h2').last()).toHaveCSS('margin-left',`${base}px`)
    if (native && tabs===2) await page.screenshot({path:info.outputPath('inherited-indent-paste.png')})
    expect(errors).toEqual([])
  })
}

for (const native of [true,false]) for (const tabs of [0,1,2,3]) {
  test(`mixed source first-line and block indents align to the first Tab text position (${native?'native':'HTML'}, ${tabs} Tab)`,async({page}) => {
    const html = '<p style="text-indent:32px;">12312</p><p style="margin-left:32px;text-indent:32px;">23123</p><p style="margin-left:32px;">3213</p><p><br></p>'
    const {editor,errors} = await fixture(page,html,tabs===3)
    const texts = ['12312','23123','3213']
    const sourceLefts = await Promise.all(texts.map(text => textLeft(editor.getByText(text,{exact:true}))))
    await select(editor.locator('p').first(),editor.locator('p').nth(2),'end')
    const data = await copy(editor)
    if (!native) delete data['application/x-slate-fragment']
    const target = editor.locator('p').last()
    await select(target)
    let firstTabLeft = 0
    for(let i=0;i<tabs;i++) {
      await page.keyboard.press('Tab')
      if (i===0) firstTabLeft = await textLeft(target)
    }
    await paste(editor,data)
    const expected = sourceLefts.map(left => tabs<2 ? left : firstTabLeft+left-Math.min(...sourceLefts))
    const check = async() => {
      for(let i=0;i<texts.length;i++) {
        await expect(editor.getByText(texts[i]!,{exact:true})).toHaveCount(2)
        expect(await textLeft(editor.getByText(texts[i]!,{exact:true}).last())).toBeCloseTo(expected[i]!,1)
        expect(await textLeft(editor.getByText(texts[i]!,{exact:true}).first())).toBeCloseTo(sourceLefts[i]!,1)
      }
    }
    await check()
    await page.keyboard.press('Control+z')
    await expect(editor.locator('p')).toHaveCount(4)
    await paste(editor,data)
    await check()
    expect(errors).toEqual([])
  })
}
