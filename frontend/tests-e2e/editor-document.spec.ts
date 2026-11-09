import {test,expect,type Page} from '@playwright/test'
async function open(page:Page,content='<p>保留开头</p><p></p>',url='/create-article?id=42') {
 await page.addInitScript(()=>{localStorage.setItem('userId','7');localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Date.now()/1000+3600}))}.test`)})
 await page.route('**/api/**',route=>{const path=new URL(route.request().url()).pathname;let data:any=[];if(path.endsWith('/article/42/edit'))data={articleId:'42',title:'测试文档',summary:'摘要保留',content,status:0,revisionId:'r1',lockVersion:1};if(path.endsWith('/user/space/7'))data={role:0,status:1};return route.fulfill({json:{code:200,data}})})
 await page.goto(url);const editor=page.locator('[data-slate-editor]');await expect(editor).toBeVisible();if(url.includes('id=42'))await expect(editor).toContainText('保留开头');return editor
}
test('document canvas, title entry, summary/settings and slash keyboard undo',async({page},info)=>{
 const editor=await open(page)
 await expect(page.locator('.summary-input')).toBeHidden();await page.getByRole('button',{name:'编辑摘要',exact:true}).click();await expect(page.locator('.summary-input')).toHaveValue('摘要保留')
 await expect(page.locator('.editor-sidebar')).toBeVisible();await expect(page.getByRole('button',{name:'发布设置',exact:true})).toHaveCount(0)
 await page.locator('.title-input').press('Enter');await expect(editor).toBeFocused()
 await editor.locator('p').last().click();await page.keyboard.type('/h2');await expect(page.getByRole('listbox',{name:'插入块'})).toBeVisible();await page.keyboard.press('Enter');await page.keyboard.type('二级标题');await expect(editor.locator('h2')).toHaveText('二级标题')
 await page.keyboard.press('Enter');await page.keyboard.type('正文续写');await expect(editor.locator('p').last()).toContainText('正文续写')
 await page.keyboard.press('Enter');await page.keyboard.type('/quote');await page.getByRole('option',{name:'引用',exact:true}).click();await expect(editor.locator('blockquote')).toHaveCount(1);await page.keyboard.press('Control+z');await expect(editor).toContainText('/quote');await expect(editor.locator('blockquote')).toHaveCount(0)
 const styles=await page.locator('.w-e-scroll').evaluate(el=>({overflow:getComputedStyle(el).overflowY,height:el.clientHeight,scroll:el.scrollHeight}));expect(styles.overflow).toBe('visible')
 await page.screenshot({path:info.outputPath('editor-document-desktop.png'),fullPage:true})
})
test('slash escape ordinary slash fullscreen and mobile',async({page},info)=>{
 await page.setViewportSize({width:390,height:844});const editor=await open(page)
 await editor.locator('p').last().click();await page.keyboard.type('/');await expect(page.getByRole('listbox')).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByRole('listbox')).toBeHidden();await page.keyboard.type('path/part');await expect(page.getByRole('listbox')).toBeHidden()
 await page.locator('.toolbar [data-menu-key="fullScreen"]').click();await expect(page.locator('.is-fullscreen')).toBeVisible();await editor.locator('p').last().click();await page.keyboard.press('End');await page.keyboard.press('Enter');await page.keyboard.type('/todo');await expect(page.getByRole('listbox')).toBeVisible();await page.keyboard.press('Enter');await expect(editor.locator('input[type="checkbox"]')).toHaveCount(1)
 await page.screenshot({path:info.outputPath('editor-document-mobile-fullscreen.png')});await page.getByRole('button',{name:/退出全屏/}).click();await expect(page.locator('.is-fullscreen')).toHaveCount(0)
})

for(const url of ['/create-article','/edit-article?id=42'])for(const width of [1440,390,320]) {
 test(`article settings stay visible without a toggle at ${width}px on ${url}`,async({page},info)=>{
  await page.setViewportSize({width,height:1000});await open(page,undefined,url)
  const sidebar=page.locator('.editor-sidebar'),main=page.locator('.editor-main')
  await expect(sidebar).toBeVisible()
  await expect(sidebar.locator('.cover-upload')).toBeVisible()
  await expect(sidebar.getByRole('combobox',{name:'文章分类'})).toBeVisible()
  await expect(sidebar.locator('.tag-input')).toBeVisible()
  await expect(page.getByRole('button',{name:'发布设置',exact:true})).toHaveCount(0)
  const content=await main.boundingBox(),settings=await sidebar.boundingBox()
  if(width>1000){expect(settings!.x).toBeGreaterThanOrEqual(content!.x+content!.width);expect(Math.abs(settings!.y-content!.y)).toBeLessThan(2)}
  else expect(settings!.y).toBeGreaterThanOrEqual(content!.y+content!.height)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  if(width===320)await expect(page.locator('.article-rich-editor [data-menu-key="fullScreen"]')).toBeInViewport()
  await page.screenshot({path:info.outputPath('article-settings-layout.png'),fullPage:true})
 })
}
