import { test, expect, type Page } from '@playwright/test'
import { deflateSync } from 'node:zlib'

// Local generated fixture; no model calls or writes to the real application.
const imageUrl = '/uploads/comments/7/2026/10/20/00000000000000000000000000000001.png'
function png(width=240,height=120) {
  const crc = (buffer: Buffer) => { let c = 0xffffffff; for (const b of buffer) { c ^= b; for(let i=0;i<8;i++) c=(c>>>1)^((c&1)?0xedb88320:0) }; return (c^0xffffffff)>>>0 }
  const chunk = (name: string, data: Buffer) => { const type=Buffer.from(name), size=Buffer.alloc(4), check=Buffer.alloc(4); size.writeUInt32BE(data.length); check.writeUInt32BE(crc(Buffer.concat([type,data]))); return Buffer.concat([size,type,data,check]) }
  const header=Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height,4); header[8]=8; header[9]=2
  const stride=1+width*3, rows=Buffer.alloc(stride*height)
  for(let y=0;y<height;y++) for(let x=0;x<width;x++) { const p=y*stride+1+x*3; rows[p]=190; rows[p+1]=230; rows[p+2]=80 }
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(rows)),chunk('IEND',Buffer.alloc(0))])
}
const picture={ name:'comment.png', mimeType:'image/png', buffer:png() }
async function fixture(page: Page, mobile=false, auth=true) {
  const writes:any[]=[], items:any[]=[], replies:any[]=[], errors:string[]=[], uploads:string[]=[]
  let failUpload=false, waitUpload:Promise<void>|undefined, release:()=>void=()=>{}
  page.on('pageerror',error=>errors.push(error.message))
  await page.setViewportSize(mobile?{width:390,height:844}:{width:1500,height:1000})
  await page.emulateMedia({reducedMotion:'reduce'})
  if(auth) await page.addInitScript(()=>{localStorage.setItem('token',`eyJhbGciOiJIUzI1NiJ9.${btoa(JSON.stringify({userId:'7',exp:Math.floor(Date.now()/1000)+3600}))}.fixture`);localStorage.setItem('userId','7');localStorage.setItem('nickName','测试读者')})
  await page.route('**/uploads/**',route=>route.fulfill({contentType:'image/png',body:png()}))
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()), path=url.pathname
    let data:any=[],code=200,message=''
    if(path.endsWith('/article/detail/42'))data={articleId:'42',title:'评论图片测试',authorName:'示例作者',authorId:'9',canReadFull:true,tags:[],content:'<h2>围绕原文交流</h2><p>依赖该任务的后续任务不会执行。</p><p>独立任务仍可以继续执行。</p>'}
    else if(path.endsWith('/file/upload-comment-image')) { uploads.push(path); if(waitUpload)await waitUpload; if(failUpload){code=400;message='上传失败，请重新选择';failUpload=false}else data={url:imageUrl} }
    else if(path.endsWith('/comment/create')) { const payload=route.request().postDataJSON();writes.push(payload);data={...payload,commentId:String(100+writes.length),userId:'7',userNickName:'测试读者',likeCount:0,replyCount:0,createTime:'2026-10-20 12:00'}; if(payload.parentId)replies.push(data);else items.unshift(data) }
    else if(path.endsWith('/comment/quote-markers'))data={records:items.filter(c=>c.quote).map(c=>({commentId:c.commentId,quote:c.quote})),nextCursor:''}
    else if(path.endsWith('/comment/replies'))data={records:replies,total:replies.length,current:1,pages:1}
    else if(path.endsWith('/comment/list')||path.endsWith('/comment/quotes')){const list=items.filter(c=>!path.endsWith('/comment/quotes')||c.quote);data={records:list,total:list.length,current:1,pages:1}}
    else if(path.endsWith('/view'))data={viewCount:1}
    else if(path.startsWith('/api/reading/'))data={sessionId:'fixture',sessionToken:'fixture',level:0,totalSeconds:0,nextLevel:1,secondsToNext:1800,rules:[]}
    else if(path.endsWith('unread-count'))data=0
    await route.fulfill({json:{code,data,message}})
  })
  await page.goto('/article/42'); await expect(page.locator('.article-content')).toBeVisible()
  return {writes,errors,uploads,items,fail:()=>{failUpload=true},delay:()=>{waitUpload=new Promise(resolve=>{release=resolve})},release:()=>{release();waitUpload=undefined}}
}
async function annotation(page: Page) {
  await page.locator('.article-content p').first().scrollIntoViewIfNeeded()
  await page.locator('.article-content p').first().evaluate(p=>{const range=document.createRange();range.selectNodeContents(p);getSelection()!.removeAllRanges();getSelection()!.addRange(range);document.dispatchEvent(new Event('selectionchange'))})
  await page.getByRole('button',{name:/评论所选内容/}).click()
  return page.getByRole('dialog',{name:'划词评论',exact:true})
}
async function pasteImage(input: ReturnType<Page['locator']>) {
  await input.evaluate((element,base64)=>{const data=new DataTransfer(),bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));data.items.add(new File([bytes],'paste.png',{type:'image/png'}));element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}))},picture.buffer.toString('base64'))
}

async function assertFullscreenPreview(page: Page) {
  const viewer=page.locator('.el-image-viewer__wrapper'), viewport=page.viewportSize()!
  await expect(viewer).toBeVisible();await expect(viewer).toHaveCSS('position','fixed')
  // The component animates in from -20px; assess its final layout after entering.
  await expect.poll(async()=>{
    const bounds=await viewer.boundingBox()
    return bounds && [Math.round(bounds.x),Math.round(bounds.y),Math.round(bounds.width),Math.round(bounds.height)]
  }).toEqual([0,0,viewport.width,viewport.height])
  await expect(viewer.locator('.el-image-viewer__mask')).toHaveCSS('position','absolute')
  await expect(viewer.locator('.el-image-viewer__mask')).toHaveCSS('background-color','rgb(0, 0, 0)')
  const close=viewer.locator('.el-image-viewer__close'), actions=viewer.locator('.el-image-viewer__actions')
  await expect(close).toBeInViewport();await expect(actions).toBeInViewport()
  expect((await close.boundingBox())!.x).toBeGreaterThan(viewport.width/2)
  const image=viewer.locator('img').first()
  await expect.poll(()=>image.evaluate(img=>img.complete&&img.naturalWidth>0)).toBe(true)
  const box=(await image.boundingBox())!
  expect(box.width).toBeLessThanOrEqual(viewport.width+1);expect(box.height).toBeLessThanOrEqual(viewport.height+1)
  expect(box.x+box.width/2).toBeCloseTo(viewport.width/2,0)
  expect(box.y+box.height/2).toBeCloseTo(viewport.height/2,0)
  // The phone comment drawer has its own stacking layer; the image must be above it.
  await expect.poll(()=>image.evaluate(img=>{
    const rect=img.getBoundingClientRect()
    return document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2)===img
  })).toBe(true)
}

for(const mobile of [false,true])for(const portrait of [false,true])test(`large image preview stays within the viewport (${mobile?'phone':'desktop'}, ${portrait?'portrait':'landscape'})`,async({page})=>{
  const state=await fixture(page,mobile)
  state.items.push({commentId:'101',userId:'7',userNickName:'测试读者',content:'图片预览',imgPath:imageUrl,replyCount:0,createTime:'2026-10-20 12:00'})
  const bytes=portrait?png(800,2400):png(2400,1400)
  await page.route('**/uploads/**',route=>route.fulfill({contentType:'image/png',body:bytes}))
  await page.reload();if(mobile)await page.locator('.mobile-comment-btn').click()
  const picture=page.locator(mobile?'.panel-content .comment-picture':'.comment-section .comment-picture')
  await picture.scrollIntoViewIfNeeded()
  const before=await page.evaluate(()=>({scrollY,documentHeight:document.documentElement.scrollHeight}))
  await picture.click();await assertFullscreenPreview(page)
  expect(await page.evaluate(()=>({scrollY,documentHeight:document.documentElement.scrollHeight}))).toEqual(before)
  await page.screenshot({path:`../temp/comment-preview-${mobile?'phone':'desktop'}-${portrait?'portrait':'landscape'}.png`,animations:'disabled'})
  const image=page.locator('.el-image-viewer__wrapper img')
  await page.locator('.el-image-viewer__actions__inner .el-icon').nth(1).click()
  await expect.poll(()=>image.evaluate(img=>img.style.transform)).toContain('scale(1.2)')
  if(portrait)await page.keyboard.press('Escape')
  else await page.locator('.el-image-viewer__close').click()
  await expect(page.locator('.el-image-viewer__wrapper')).toHaveCount(0)
  expect(state.errors).toEqual([])
})

for(const mobile of [false,true])test(`normal comments and replies support pictures (${mobile?'phone':'desktop'})`,async({page})=>{
  const state=await fixture(page,mobile)
  if(mobile)await page.locator('.mobile-comment-btn').click()
  const composer=page.locator(mobile?'.panel-input':'.top-input'), input=composer.getByPlaceholder('发一条友善的评论')
  const list=page.locator(mobile?'.panel-content':'.comment-section')
  await input.focus();state.delay()
  await composer.getByLabel('选择评论图片').setInputFiles(picture)
  await expect(composer.getByRole('button',{name:/上传中/})).toBeVisible()
  await expect(composer.getByRole('button',{name:'发布',exact:true})).toBeDisabled();expect(state.writes).toHaveLength(0)
  state.release();await expect(composer.getByRole('button',{name:'移除评论图片'})).toBeVisible()
  await composer.getByRole('button',{name:'发布',exact:true}).click()
  await expect(list.locator('.comment-item')).toHaveCount(1)
  expect(state.writes[0]).toMatchObject({content:'',imgPath:imageUrl})
  const comment=list.locator('.comment-item').first()
  await comment.getByRole('button',{name:'查看评论图片'}).click();await assertFullscreenPreview(page);await page.keyboard.press('Escape');await expect(page.locator('.el-image-viewer__wrapper')).toHaveCount(0)
  await comment.locator('.reply-btn').first().click()
  const reply=comment.locator('.inline-reply-box')
  await pasteImage(reply.locator('textarea'));await expect(reply.getByRole('button',{name:'移除评论图片'})).toBeVisible()
  await reply.getByRole('button',{name:'发布',exact:true}).click()
  await expect(comment.locator('.reply-item .comment-picture')).toHaveCount(1)
  expect(state.writes[1]).toMatchObject({parentId:'101',content:'',imgPath:imageUrl})
  await page.reload();if(mobile)await page.locator('.mobile-comment-btn').click()
  await expect(list.locator('.comment-item .comment-picture')).toHaveCount(1)
  expect(state.errors).toEqual([])
})

for(const mobile of [false,true])test(`selection comments and replies display uploaded pictures (${mobile?'phone':'desktop'})`,async({page})=>{
  const state=await fixture(page,mobile),panel=await annotation(page),composer=panel.locator('.annotation-composer')
  await composer.getByLabel('选择评论图片').setInputFiles(picture)
  await expect(composer.getByRole('button',{name:'移除评论图片'})).toBeVisible()
  await composer.getByRole('button',{name:'发布评论',exact:true}).click()
  await expect(panel.locator('.annotation-thread .comment-picture')).toHaveCount(1)
  expect(state.writes[0]).toMatchObject({content:'',imgPath:imageUrl,quote:{exact:'依赖该任务的后续任务不会执行。'}})
  await panel.getByRole('button',{name:/^回复/}).click()
  const reply=panel.locator('.annotation-replies')
  await pasteImage(reply.locator('textarea'));await expect(reply.getByRole('button',{name:'移除评论图片'})).toBeVisible()
  await reply.getByRole('button',{name:'发布回复'}).click();await expect(reply.locator('.annotation-reply .comment-picture')).toHaveCount(1)
  expect(state.writes[1]).toMatchObject({parentId:'101',imgPath:imageUrl});expect(state.writes[1].quote).toBeUndefined()
  await reply.locator('.annotation-reply').getByRole('button',{name:'查看评论图片'}).click();await assertFullscreenPreview(page);await page.keyboard.press('Escape')
  await expect(panel).toBeVisible();await page.screenshot({path:`../temp/comment-images-${mobile?'phone':'desktop'}.png`,animations:'disabled'})
  await page.reload();await page.getByRole('button',{name:/划词评论/}).first().click();await expect(panel.locator('.annotation-thread .comment-picture')).toHaveCount(1)
  expect(state.errors).toEqual([])
})

test('invalid files and failed uploads preserve text; retry and removal work',async({page})=>{
  const state=await fixture(page),panel=await annotation(page),composer=panel.locator('.annotation-composer'),input=composer.getByRole('textbox',{name:'评论内容',exact:true})
  await input.fill('文字不能丢')
  await composer.getByLabel('选择评论图片').setInputFiles({name:'bad.svg',mimeType:'image/svg+xml',buffer:Buffer.from('<svg/>')})
  await expect(composer.getByRole('alert')).toContainText('JPG');expect(state.uploads).toHaveLength(0)
  await composer.getByLabel('选择评论图片').setInputFiles({name:'large.png',mimeType:'image/png',buffer:Buffer.alloc(5*1024*1024+1)})
  await expect(composer.getByRole('alert')).toContainText('5MB');expect(state.uploads).toHaveLength(0)
  state.fail();await composer.getByLabel('选择评论图片').setInputFiles(picture);await expect(composer.getByRole('alert')).toContainText('上传失败');await expect(input).toHaveValue('文字不能丢')
  await composer.getByLabel('选择评论图片').setInputFiles(picture);await expect(composer.getByRole('button',{name:'移除评论图片'})).toBeVisible()
  await composer.getByRole('button',{name:'移除评论图片'}).click();await expect(input).toHaveValue('文字不能丢')
  await composer.getByRole('button',{name:'发布评论',exact:true}).click();expect(state.writes[0]).toMatchObject({content:'文字不能丢',imgPath:null})
  expect(state.errors).toEqual([])
})

test('a canceled upload cannot attach its image to a new selection comment',async({page})=>{
  const state=await fixture(page),panel=await annotation(page),composer=panel.locator('.annotation-composer')
  state.delay();await composer.getByLabel('选择评论图片').setInputFiles(picture)
  await expect(composer.getByRole('button',{name:/上传中/})).toBeVisible()
  await composer.getByRole('button',{name:'取消',exact:true}).click();state.release()
  await panel.getByRole('button',{name:'关闭划词评论'}).click();await annotation(page)
  await expect(composer.getByRole('button',{name:'添加图片'})).toBeVisible();await expect(composer.getByRole('button',{name:'移除评论图片'})).toHaveCount(0)
  await expect(composer.getByRole('button',{name:'发布评论',exact:true})).toBeDisabled();expect(state.writes).toHaveLength(0);expect(state.errors).toEqual([])
})

test('guests are asked to sign in before uploading a comment image',async({page})=>{
  const state=await fixture(page,false,false),panel=await annotation(page)
  await panel.getByLabel('选择评论图片').setInputFiles(picture)
  await expect(page.locator('.modern-dialog')).toBeVisible()
  expect(state.uploads).toHaveLength(0);expect(state.writes).toHaveLength(0);expect(state.errors).toEqual([])
})
