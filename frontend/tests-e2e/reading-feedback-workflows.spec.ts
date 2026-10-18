import { test, expect, type Page } from '@playwright/test'

const rid='117f57d9-93d7-42de-8de4-491eb297b823', generation='7364b086-ea4e-442a-aa59-83ec2d2dba48'
const sections=Array.from({length:24},(_,i)=>`第 ${i+1} 节：Agent 的工具与记忆`)
const content=sections.map(text=>`<h2>${text}</h2><p>${'正文阅读和目录验收。'.repeat(90)}</p>`).join('')
const answer='这是一段代码示例。\n\n```java\npublic class Demo {\n    String value = "hello";\n}\n```'

async function fixture(page:Page, options:{canRead?:boolean;failFirst?:boolean;conflict?:boolean}={}) {
 await page.emulateMedia({reducedMotion:'reduce'})
 await page.addInitScript(()=>{localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600}))}.test`);localStorage.setItem('userId','7');localStorage.setItem('nickName','验收用户')})
 const errors:string[]=[],writes:any[]=[],counts={article:0,notifications:0,detail:0},state={content,review:'pending',version:0,note:''}
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/api/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname;let data:any=[]
  if(path.endsWith('/article/detail/42')){counts.article++;if(options.failFirst&&counts.article===1)return route.abort('failed');data={articleId:'42',title:'阅读流程验收',content:state.content,canReadFull:true,authorId:'8',authorName:'示例作者',tags:[]}}
  else if(path.endsWith('/notification/list')){counts.notifications++;if(options.failFirst&&counts.notifications===1)return route.abort('failed');data={records:[{notificationId:'1',senderId:'8',senderNickname:'示例用户',content:'赞了你的文章',articleId:'42',isRead:1,type:2}],total:1,pages:1}}
  else if(path.endsWith('/admin/me'))data={userId:'7',permissions:['overview.read','metrics.read',...(options.canRead===false?[]:['feedback.read','feedback.manage'])]}
  else if(path.endsWith('/admin/overview'))data={users:1,published:1,readingSeconds:0,rules:[]}
  else if(path.endsWith('/admin/agent-metrics'))data=null
  else if(path.endsWith('/admin/agent-feedback'))data={rows:[{run_id:rid,rating:'problem',reason:'citation',review_state:state.review,updated_at:'2026-10-17T10:00:00'}],counts:[{rating:'problem',reason:'citation',count:1}],total:1}
  else if(path.endsWith(`/admin/agent-feedback/${rid}/review`)){writes.push(request.postDataJSON());if(options.conflict)return route.fulfill({status:409,json:{code:409,message:'Agent 运行状态已变化，请刷新后重试'}});state.review=request.postDataJSON().state;state.note=request.postDataJSON().note;state.version++;data={version:state.version,state:state.review}}
  else if(path.endsWith(`/admin/agent-feedback/${rid}`)){counts.detail++;data={feedback:{run_id:rid,user_id:'8',run_status:'succeeded',review_state:state.review,review_version:state.version,feedback_generation:generation,review_note:state.note,conversation_status:1,comment:'来源没有支持这个具体数字'},question:{content:'请解释 Agent 的工具调用'},answer:{content:answer},events:[{event_id:1,node:'main_agent',status:'completed',duration_ms:500}],history:state.review==='resolved'?[{actor_id:'7',to_state:'resolved',note:state.note,created_at:'2026-10-17T10:10:00'}]:[]}}
  else if(path.endsWith('/user/space/7'))data={userId:'7',nickName:'验收用户',role:2,status:1}
  else if(path.endsWith('/agent/library'))data={rows:url.searchParams.get('scope')==='general'?[{conversationId:'101',title:'代码验收'}]:[],total:1}
  else if(path.endsWith('/agent/conversations/101'))data={conversationId:'101',title:'代码验收'}
  else if(path.endsWith('/messages'))data=[{role:'user',content:'给个代码例子',messageId:'1001'},{role:'assistant',content:answer,messageId:'1002',runId:rid}]
  else if(path.endsWith('/questions'))data={items:[],hasMore:false}
  else if(path.endsWith('/feedback')||path.endsWith('/run'))data=null
  else if(path.endsWith('/agent/run-overview'))data={items:[]}
  else if(path.endsWith('/comment/list'))data={records:[],total:0,pages:1}
  else if(path.endsWith('/view'))data={viewCount:1}
  else if(path.endsWith('/reading/sessions')||path.endsWith('/reading/heartbeat'))data={sessionId:'qa-reading-session',level:0,totalSeconds:0,nextLevel:1,secondsToNext:60,rules:[{level:0,minSeconds:0},{level:1,minSeconds:60}]}
  else if(path.endsWith('/unread-count')||path.endsWith('/total-unread-count'))data=0
  await route.fulfill({json:{code:200,data}})
 })
 return {errors,writes,counts,state}
}

test('article and notifications expose recoverable errors instead of an empty page',async({page})=>{
 const {errors,counts}=await fixture(page,{failFirst:true})
 await page.goto('/article/42');await expect(page.getByRole('alert')).toContainText('文章暂时无法加载')
 await page.getByRole('button',{name:'重新加载',exact:true}).click();await expect(page.getByRole('heading',{name:'阅读流程验收',exact:true})).toBeVisible();expect(counts.article).toBe(2)
 await page.goto('/notifications');await expect(page.getByRole('alert')).toContainText('通知暂时无法加载');await expect(page.getByText('暂无通知',{exact:true})).toHaveCount(0)
 await page.getByRole('button',{name:'重新加载',exact:true}).click();await expect(page.getByText('赞了你的文章',{exact:true})).toBeVisible();expect(counts.notifications).toBe(2);expect(errors).toEqual([])
})

test('mobile outline closes after selection and lands below reading controls',async({page})=>{
 await page.setViewportSize({width:390,height:844});const {errors}=await fixture(page)
 await page.goto('/article/42');await page.getByRole('button',{name:'目录',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'文章目录',exact:true});await expect(dialog).toBeVisible()
 await dialog.getByRole('link',{name:sections[18],exact:true}).click();await expect(dialog).toHaveCount(0)
 const heading=page.locator('.article-content h2').nth(18)
 await expect.poll(async()=>Math.round((await heading.boundingBox())!.y-(await page.locator('.article-reading-tools').boundingBox())!.y-(await page.locator('.article-reading-tools').boundingBox())!.height)).toBe(16)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
 await page.screenshot({path:'../logs/mobile-article-outline.png',animations:'disabled'});expect(errors).toEqual([])
})

test('reading position resumes after refresh; section links open the right chapter and edited articles discard old positions',async({page,context})=>{
 await page.setViewportSize({width:1440,height:900});await context.grantPermissions(['clipboard-read','clipboard-write'])
 const {errors,state}=await fixture(page);await page.goto('/article/42')
 await page.getByRole('navigation',{name:'文章目录',exact:true}).getByRole('link',{name:sections[8],exact:true}).click()
 await page.mouse.move(800,600);await page.mouse.wheel(0,120);await page.waitForTimeout(500)
 const before=(await page.locator('.article-content h2').nth(8).boundingBox())!.y
 await page.reload();await expect(page.getByRole('status').filter({hasText:'上次读到'})).toContainText(sections[8]);await page.getByRole('button',{name:'继续阅读',exact:true}).click()
 await expect.poll(async()=>Math.abs((await page.locator('.article-content h2').nth(8).boundingBox())!.y-before)).toBeLessThan(3)
 await page.getByRole('button',{name:'分享本节',exact:true}).click();const link=await page.evaluate(()=>navigator.clipboard.readText());expect(link).toContain('#section-')
 await page.goto(link);await expect.poll(async()=>Math.round((await page.locator('.article-content h2').nth(8).boundingBox())!.y-(await page.locator('.article-reading-tools').boundingBox())!.y-(await page.locator('.article-reading-tools').boundingBox())!.height)).toBe(16)
  await page.reload();await expect.poll(async()=>Math.round((await page.locator('.article-content h2').nth(8).boundingBox())!.y-(await page.locator('.article-reading-tools').boundingBox())!.y-(await page.locator('.article-reading-tools').boundingBox())!.height)).toBe(16)
  state.content='<p>文章已更新</p>'+content;await page.goto('/article/42');await expect(page.getByRole('status').filter({hasText:'上次读到'})).toHaveCount(0);expect(errors).toEqual([])
})

test('AI answers offer the shared code viewer and copy the original answer',async({page,context})=>{
 await page.setViewportSize({width:1440,height:900});await context.grantPermissions(['clipboard-read','clipboard-write']);const {errors}=await fixture(page)
 await page.goto('/ai-chat?conversationId=101');await page.getByRole('button',{name:'放大第 1 个代码块',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'代码放大查看',exact:true});await expect(dialog.locator('code')).toContainText('public class Demo')
 await page.keyboard.press('Escape');await page.getByRole('button',{name:'复制回答',exact:true}).click();expect((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n')).toBe(answer);expect(errors).toEqual([])
})

test('feedback detail displays the reported turn and persists a review with its original version',async({page})=>{
 await page.setViewportSize({width:1440,height:900});const {errors,writes}=await fixture(page)
 await page.goto('/admin?section=agentMetrics');await page.getByRole('button',{name:'查看详情',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'回答反馈详情',exact:true});await expect(dialog).toContainText('来源没有支持这个具体数字');await expect(dialog).toContainText('请解释 Agent 的工具调用')
 await dialog.getByText('执行过程 · 最近 1 条记录',{exact:true}).click();await expect(dialog).toContainText('Main 决策')
 await dialog.getByRole('combobox',{name:'处理状态',exact:true}).click();await page.getByRole('option',{name:'已解决',exact:true}).click()
 await expect(dialog.getByRole('button',{name:'保存处理结果',exact:true})).toBeDisabled();await dialog.getByRole('textbox',{name:'处理说明',exact:true}).fill('修正引用并加入回归用例')
 await dialog.getByRole('button',{name:'保存处理结果',exact:true}).click();await expect.poll(()=>writes.length).toBe(1);await expect(dialog.getByText('处理记录 · 最近 1 次',{exact:true})).toBeVisible()
 expect(writes[0]).toMatchObject({state:'resolved',note:'修正引用并加入回归用例',version:0,generation});expect(writes[0].commandId).toMatch(/^[a-f0-9-]{36}$/)
 await page.screenshot({path:'../logs/answer-feedback-review.png',animations:'disabled'});expect(errors).toEqual([])
})

test('metadata-only operators cannot open private feedback details',async({page})=>{
 const {counts,errors}=await fixture(page,{canRead:false});await page.goto('/admin?section=agentMetrics')
 await expect(page.getByText('当前账号可查看统计；查看问答内容需要反馈查看权限。',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'查看详情',exact:true})).toHaveCount(0);expect(counts.detail).toBe(0);expect(errors).toEqual([])
})

test('a changed feedback cannot be overwritten from a stale admin form',async({page})=>{
 const {writes}=await fixture(page,{conflict:true});await page.goto('/admin?section=agentMetrics');await page.getByRole('button',{name:'查看详情',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'回答反馈详情',exact:true});await dialog.getByRole('button',{name:'保存处理结果',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('反馈已更新');await expect(dialog.getByRole('button',{name:'保存处理结果',exact:true})).toBeDisabled();expect(writes.length).toBe(1)
 await dialog.getByRole('button',{name:'重新读取最新反馈',exact:true}).click();await expect(dialog.getByRole('alert')).toHaveCount(0)
})
