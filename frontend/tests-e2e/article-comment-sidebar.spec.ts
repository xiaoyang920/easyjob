import { test, expect, type Page } from '@playwright/test'

test.use({ actionTimeout: 8000 })
const imageUrl='/uploads/comments/7/2026/10/20/00000000000000000000000000000001.png'
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jC1sAAAAASUVORK5CYII=','base64')
async function fixture(page:Page,mobile=false) {
  const errors:string[]=[], writes:any[]=[], sorts:string[]=[], replies:any[]=[]
  const items=Array.from({length:13},(_,index)=>({commentId:String(101+index),userId:'7',userNickName:'测试读者',content:`已有评论 ${index+1}`,replyCount:0,likeCount:0,createTime:'2026-10-20 12:00'}))
  let fail=false
  await page.setViewportSize(mobile?{width:390,height:844}:{width:1500,height:1000})
  await page.emulateMedia({reducedMotion:'reduce'})
  page.on('pageerror',error=>errors.push(error.message))
  await page.addInitScript(()=>{localStorage.setItem('token',`qa.${btoa(JSON.stringify({userId:'7',exp:Math.floor(Date.now()/1000)+3600}))}.fixture`);localStorage.setItem('userId','7')})
  await page.routeWebSocket(/\/ws\/article/,()=>{})
  await page.route('**/uploads/**',route=>route.fulfill({contentType:'image/png',body:png}))
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname
    let data:any=[],code=200,message=''
    if(path.endsWith('/article/detail/42'))data={articleId:'42',title:'阅读与评论',authorId:'9',canReadFull:true,requiredLevel:0,tags:[],content:'<h2>阅读开头</h2>'+Array.from({length:30},(_,i)=>`<p>正文第 ${i+1} 段。可以在阅读时打开评论，独立滚动评论列表，不必跳到文章底部。</p>`).join('')}
    else if(path.endsWith('/comment/list')){
      sorts.push(url.searchParams.get('sort')||'')
      if(fail){code=503;message='评论暂时无法读取';fail=false}
      const current=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('size')||10)
      data={records:items.slice((current-1)*size,current*size),total:items.length,current,pages:Math.ceil(items.length/size)}
    }
    else if(path.endsWith('/comment/create')){const payload=route.request().postDataJSON();writes.push(payload);data={...payload,commentId:String(201+writes.length),userId:'7',userNickName:'测试读者',replyCount:0,createTime:'2026-10-20 12:00'};if(payload.parentId)replies.push(data);else items.unshift(data)}
    else if(path.endsWith('/comment/replies'))data={records:replies,current:1,pages:1,total:replies.length}
    else if(path.endsWith('/comment/quotes')||path.endsWith('/comment/quote-markers'))data={records:[],total:0,current:1,pages:1,nextCursor:''}
    else if(path.endsWith('/file/upload-comment-image'))data={url:imageUrl}
    else if(path.startsWith('/api/reading/'))data={sessionId:'fixture',sessionToken:'fixture',level:0,totalSeconds:0,rules:[]}
    else if(path.endsWith('/run'))data=null
    else if(path.endsWith('/agent/run-overview'))data={items:[]}
    else if(path.endsWith('/article/list'))data={records:[],total:0,current:1,pages:1}
    else if(path.endsWith('unread-count'))data=0
    await route.fulfill({json:{code,data,message}})
  })
  await page.goto('/article/42');await expect(page.locator('.article-content')).toBeVisible()
  if(!mobile)await expect(page.locator('.comment-section .comment-item')).toHaveCount(10)
  return {errors,writes,sorts,fail:()=>{fail=true}}
}
const sidebar=(page:Page)=>page.getByRole('dialog',{name:'文章评论',exact:true})

test('shortcut opens a sidebar without moving the article, preserves the composer, and restores focus',async({page})=>{
  const state=await fixture(page)
  await page.locator('.article-content p').nth(12).scrollIntoViewIfNeeded()
  await page.locator('.article-content p').nth(12).click()
  const before=await page.evaluate(()=>({scrollY,height:document.documentElement.scrollHeight}))
  await page.keyboard.press('Control+Alt+m')
  const panel=sidebar(page),input=panel.getByPlaceholder('发一条友善的评论')
  await expect(panel).toHaveCSS('position','fixed');await expect(input).toBeFocused();await expect(input).toBeInViewport()
  expect(await page.evaluate(()=>({scrollY,height:document.documentElement.scrollHeight}))).toEqual(before)
  await input.fill('读到这里的想法，先保留')
  await page.keyboard.press('Escape');await expect(panel).toHaveCount(0)
  await expect(page.locator('.top-input textarea')).toHaveValue('读到这里的想法，先保留')
  await page.getByRole('button',{name:'打开文章评论'}).click()
  await expect(input).toHaveValue('读到这里的想法，先保留')
  const box=(await panel.boundingBox())!
  expect(box.width).toBeLessThan(500);expect(box.x).toBeGreaterThan(900);expect(box.y+box.height).toBeLessThanOrEqual(1000)
  await page.screenshot({path:'../temp/article-comment-sidebar-desktop.png',animations:'disabled'})
  await panel.getByRole('button',{name:'关闭文章评论'}).click()
  await expect(page.getByRole('button',{name:'打开文章评论'})).toBeFocused()
  expect(state.writes).toHaveLength(0);expect(state.errors).toEqual([])
})

test('sidebar supports sending pictures, viewing them above the panel, replies, sorting and pagination',async({page})=>{
  const state=await fixture(page)
  await page.getByRole('button',{name:/^文章评论/}).click()
  const panel=sidebar(page),composer=panel.locator('.top-input')
  await composer.getByPlaceholder('发一条友善的评论').fill('图文评论')
  await composer.getByLabel('选择评论图片').setInputFiles({name:'comment.png',mimeType:'image/png',buffer:png})
  await expect(composer.getByRole('button',{name:'移除评论图片'})).toBeVisible()
  await composer.getByRole('button',{name:'发布',exact:true}).click()
  const comment=panel.locator('.comment-item').first()
  await expect(comment.getByText('图文评论',{exact:true})).toBeVisible()
  expect(state.writes[0]).toMatchObject({content:'图文评论',imgPath:imageUrl})
  await comment.getByRole('button',{name:'查看评论图片'}).click();await expect(page.locator('.el-image-viewer__wrapper')).toBeVisible()
  await page.keyboard.press('Escape');await expect(page.locator('.el-image-viewer__wrapper')).toHaveCount(0);await expect(panel).toBeVisible()
  await comment.locator('.reply-btn').first().click()
  await comment.locator('.inline-reply-box textarea').fill('回复仍然在这里')
  await comment.locator('.inline-reply-box').getByRole('button',{name:'发布',exact:true}).click()
  await expect(comment.getByText('回复仍然在这里',{exact:true})).toBeVisible()
  await panel.getByRole('button',{name:'最新',exact:true}).click();await expect.poll(()=>state.sorts.at(-1)).toBe('new')
  await panel.locator('.load-more-comments').click();await expect(panel.locator('.comment-item')).toHaveCount(14)
  expect(state.errors).toEqual([])
})

test('switching between comments, selection comments and AI keeps only one panel open',async({page})=>{
  const state=await fixture(page)
  await page.locator('.ask-article-ai-btn').click();await expect(page.locator('#article-ai-panel')).toBeVisible()
  await page.getByRole('button',{name:/^文章评论/}).click();await expect(sidebar(page)).toBeVisible();await expect(page.locator('#article-ai-panel')).toBeHidden()
  await sidebar(page).getByPlaceholder('发一条友善的评论').fill('切换后保留')
  await page.getByRole('button',{name:/^划词评论/}).click();await expect(sidebar(page)).toHaveCount(0)
  await expect(page.getByRole('dialog',{name:'划词评论',exact:true})).toBeVisible()
  await page.getByRole('button',{name:/^文章评论/}).click();await expect(page.getByRole('dialog',{name:'划词评论',exact:true})).toHaveCount(0)
  await expect(sidebar(page).getByPlaceholder('发一条友善的评论')).toHaveValue('切换后保留')
  expect(state.errors).toEqual([])
})

test('typing and other dialogs keep their keyboard behavior; route changes remove the shortcut',async({page})=>{
  const state=await fixture(page)
  await page.locator('.top-input textarea').focus();await page.keyboard.press('Control+Alt+m');await expect(sidebar(page)).toHaveCount(0)
  await page.locator('.article-content p').first().click();await page.keyboard.press('Control+Alt+m');await expect(sidebar(page)).toBeVisible()
  await page.keyboard.press('Escape');await expect(sidebar(page)).toHaveCount(0)
  await page.goto('/');await page.keyboard.press('Control+Alt+m');await expect(sidebar(page)).toHaveCount(0)
  expect(state.errors).toEqual([])
})

test('phone drawer focuses the composer and survives desktop resize with the same text',async({page})=>{
  const state=await fixture(page,true)
  await page.getByRole('button',{name:'打开文章评论'}).click()
  const panel=sidebar(page),input=panel.getByPlaceholder('发一条友善的评论')
  await expect(input).toBeFocused();await expect(input).toBeInViewport();await expect(page.locator('body')).toHaveCSS('overflow','hidden')
  await input.fill('手机切到桌面也保留')
  await page.screenshot({path:'../temp/article-comment-sidebar-phone.png',animations:'disabled'})
  await page.setViewportSize({width:1500,height:1000});await expect(panel).toHaveClass(/comments-sidebar/);await expect(input).toHaveValue('手机切到桌面也保留')
  await expect(page.locator('body')).not.toHaveCSS('overflow','hidden')
  await page.setViewportSize({width:390,height:600});await expect(panel).toHaveClass(/mobile-comment-panel/);await expect(input).toHaveValue('手机切到桌面也保留');await expect(input).toBeInViewport()
  await panel.getByRole('button',{name:'关闭文章评论'}).click();await expect(panel).toHaveCount(0);await expect(page.locator('body')).not.toHaveCSS('overflow','hidden')
  expect(state.errors).toEqual([])
})

test('failed comment reads can retry inside the sidebar',async({page})=>{
  const state=await fixture(page)
  await page.getByRole('button',{name:'打开文章评论'}).click();state.fail()
  await sidebar(page).getByRole('button',{name:'最新',exact:true}).click()
  await expect(sidebar(page).getByRole('alert')).toContainText('评论暂时无法读取')
  await sidebar(page).getByRole('button',{name:'重新加载'}).click();await expect(sidebar(page).getByRole('alert')).toHaveCount(0)
  await expect(sidebar(page).locator('.comment-item')).toHaveCount(10);expect(state.errors).toEqual([])
})
