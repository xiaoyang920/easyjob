import { test, expect, type Page } from '@playwright/test'

async function fixture(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600}))}.test`)
    localStorage.setItem('userId','7');localStorage.setItem('nickName','验收用户')
  })
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message))
  const messages=Array.from({length:1000},(_,i)=>({itemId:`message:${i+1}`,messageId:String(i+1),role:i%2?'assistant':'user',content:i%2?`回答 ${i+1}\n\n${'长对话窗口测试。'.repeat(80)}`:`提问 ${i+1}`}))
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname;let data:any=[]
    if(path.endsWith('/user/space/7'))data={userId:'7',nickName:'验收用户',role:1,status:1}
    else if(path.endsWith('/agent/library'))data={rows:url.searchParams.get('scope')==='general'?[{conversationId:'101',title:'长对话验收'}]:[],total:1}
    else if(path.endsWith('/agent/conversations/101'))data={conversationId:'101',title:'长对话验收'}
    else if(path.endsWith('/messages'))data={items:messages,hasOlder:false,hasNewer:false}
    else if(path.endsWith('/questions'))data={items:messages.filter(m=>m.role==='user').map(m=>({messageId:m.messageId,question:m.content})),hasMore:false,snapshot:'999'}
    else if(path.endsWith('/run'))data=null
    else if(path.endsWith('/agent/run-overview'))data={items:[]}
    else if(path.endsWith('/article/work'))data={records:[],total:0,pages:1}
    else if(path.endsWith('/total-unread-count')||path.endsWith('/unread-count'))data=0
    await route.fulfill({json:{code:200,status:'success',data}})
  })
  return errors
}

test('the same navigation and avatar survive route changes without replaying page animation',async({page})=>{
  const errors=await fixture(page)
  await page.goto('/ai-chat');await expect(page.getByRole('textbox',{name:'搜索对话'})).toBeVisible()
  const header=await page.locator('.app-header').elementHandle()
  await page.getByRole('link',{name:'草稿',exact:true}).click()
  await expect(page).toHaveURL(/\/draft-box$/)
  expect(await header!.evaluate(el=>el===document.querySelector('.app-header'))).toBe(true)
  expect(await header!.evaluate(el=>el.closest('.page-frame'))).toBeNull()
  await page.getByRole('button',{name:'账户菜单',exact:true}).hover()
  await expect(page.locator('#app-account-panel').getByRole('link',{name:'编辑资料',exact:true})).toBeVisible()
  await page.locator('.app-account-stats').hover()
  await expect(page.locator('#app-account-panel')).toBeVisible()
  expect(errors).toEqual([])
})

test('one thousand messages render a bounded window and local question jumps need no reload',async({page})=>{
  const errors=await fixture(page);await page.goto('/ai-chat?conversationId=101')
  const list=page.locator('.message-list')
  await expect(list).toHaveAttribute('data-message-count','1000')
  await expect.poll(()=>page.locator('.message-item').count()).toBeLessThan(60)
  await page.getByRole('button',{name:'跳转到第 1 个提问：提问 1',exact:true}).click()
  await expect(page.locator('[data-question-id="1"]')).toBeVisible()
  await page.getByRole('button',{name:'跳转到第 250 个提问：提问 499',exact:true}).click()
  await expect(page.locator('[data-question-id="499"]')).toBeVisible()
  await expect(list).toHaveAttribute('data-message-count','1000')
  await expect.poll(()=>page.locator('.message-item').count()).toBeLessThan(60)
  await page.screenshot({path:'../logs/virtual-message-window.png',animations:'disabled'})
  expect(errors).toEqual([])
})

test('private chat keeps its visible row when prepending crosses the virtual-window threshold',async({page})=>{
  await page.setViewportSize({width:1440,height:1000})
  await page.emulateMedia({reducedMotion:'reduce'})
  const errors=await fixture(page)
  await page.route('**/api/chat/**',async route=>{
    const url=new URL(route.request().url());let data:any=0
    if(url.pathname.endsWith('/conversations'))data=[{conversationId:'303',otherUserId:'8',otherUserName:'私信验收',unreadCount:0}]
    if(url.pathname.endsWith('/messages')){
      const older=!!url.searchParams.get('lastMessageId'),start=older?1:41
      data={records:Array.from({length:40},(_,i)=>({messageId:String(start+i),senderId:i%2?'7':'8',senderName:'私信验收',messageType:1,status:0,content:`私信 ${start+i} ${'内容。'.repeat(30)}`,createTime:'2026-10-17 12:00:00'})).reverse(),hasMore:!older}
    }
    await route.fulfill({json:{code:200,data}})
  })
  await page.goto('/chat?userId=8')
  const list=page.locator('.message-list')
  await expect(list).toHaveAttribute('data-message-count','40')
  await list.evaluate(el=>{el.scrollTop=230})
  const anchor=await list.evaluate(el=>{
    const node=Array.from(el.querySelectorAll<HTMLElement>('[data-virtual-key]')).find(n=>n.getBoundingClientRect().bottom>el.getBoundingClientRect().top)!
    return {key:node.dataset.virtualKey,top:node.getBoundingClientRect().top}
  })
  await page.getByText('加载更多消息',{exact:true}).evaluate((el:HTMLElement)=>el.click())
  await expect(list).toHaveAttribute('data-message-count','80')
  await expect.poll(()=>list.locator('[data-virtual-key]').count()).toBeLessThan(60)
  await expect.poll(async()=>Math.abs(await list.locator(`[data-virtual-key="${anchor.key}"]`).evaluate(el=>el.getBoundingClientRect().top)-anchor.top)).toBeLessThan(3)
  expect(errors).toEqual([])
})

test('first-answer timing is reported once after actual answer text is visible',async({page})=>{
  await page.setViewportSize({width:1440,height:1000})
  const errors=await fixture(page),samples:any[]=[]
  const runId='01b3e467-9daa-4ad1-b1cc-5ccfe70e38de'
  await page.route('**/delivery-metrics',async route=>{
    samples.push(route.request().postDataJSON());await route.fulfill({json:{code:200,data:true}})
  })
  await page.route('**/api/agent/chat/stream',async route=>{
    const events=['__CONV_ID__:101',`__RUN_ID__:${runId}`,'__INPUT_ID__:1001',
      '__ANSWER__:{"type":"start","mode":"direct"}',
      '__ANSWER__:{"type":"delta","seq":0,"content":"首段可见答案"}',
      '__ANSWER__:{"type":"delta","seq":1,"content":"，后续文字"}',
      '__REPLY__:{"content":"首段可见答案，后续文字"}','__PROGRESS__:done','[DONE]']
    await route.fulfill({contentType:'text/event-stream',body:events.map(e=>`data:${e}\n\n`).join('')})
  })
  await page.goto('/ai-chat?conversationId=101')
  await expect(page.locator('.message-list')).toHaveAttribute('data-message-count','1000')
  await page.getByRole('textbox',{name:'消息内容'}).fill('计时界面测试')
  await page.getByRole('button',{name:'发送消息',exact:true}).click()
  await expect(page.locator('.message-bubble').last()).toContainText('首段可见答案')
  await expect.poll(()=>samples.length).toBe(1)
  expect(samples[0].firstAnswerMs).toBeGreaterThan(0)
  expect(samples[0].firstAnswerMs).toBeLessThan(10000)
  expect(errors).toEqual([])
})
