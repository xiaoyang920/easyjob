import {test,expect,type Page} from '@playwright/test'

async function fixture(page:Page){
  await page.addInitScript(()=>{localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600}))}.test`);localStorage.setItem('userId','7');localStorage.setItem('nickName','我')})
  await page.emulateMedia({reducedMotion:'reduce'})
  const errors:string[]=[],sockets:any[]=[],sends:any[]=[],reads:any[]=[],shareRecords:any[]=[]
  page.on('pageerror',e=>errors.push(e.message));await page.routeWebSocket('**/ws/**',socket=>{if(socket.url().includes('/ws/chat'))sockets.push(socket)})
  const people:any[]=[{userId:'8',nickName:'林同学',remark:'老同学',isFollowing:true,isFollowedBy:true,isFriend:true,isBlockedByMe:false},{userId:'9',nickName:'新读者',remark:'',isFollowing:false,isFollowedBy:true,isFriend:false,isBlockedByMe:false},{userId:'10',nickName:'陌生作者',remark:'',isFollowing:false,isFollowedBy:false,isFriend:false,isBlockedByMe:false}]
  const normal:any={conversationId:'101',otherUserId:'8',otherUserName:'林同学',remark:'老同学',unreadCount:2,isMuted:false,isTop:false,requestState:'ACCEPTED',requestIncoming:false,canMessage:true,canSendRich:true,lastMessage:'分享一篇文章',lastMessageTime:'2026-10-22T10:00:00'}
  const incoming:any={conversationId:'203',otherUserId:'9',otherUserName:'新读者',unreadCount:1,isMuted:false,isTop:false,requestState:'PENDING',requestIncoming:true,requestUnseen:true,canMessage:true,canSendRich:true,lastMessage:'你好，想讨论文章',sendReason:'回复将接受此消息请求'}
  const stranger:any={conversationId:'304',otherUserId:'10',otherUserName:'陌生作者',unreadCount:0,isMuted:false,isTop:false,requestState:'NONE',requestIncoming:false,canMessage:true,canSendRich:false,sendReason:'可发送一条不超过300字的文字招呼'}
  const conversations=[normal,incoming,stranger],rows:Record<string,any[]>={
    '101':[{messageId:'1',conversationId:'101',senderId:'8',senderName:'林同学',messageType:1,content:'这篇文章可以一起讨论',status:0,createTime:'2026-10-22T10:00:00'},{messageId:'2',conversationId:'101',senderId:'8',senderName:'林同学',messageType:3,content:'55',article:{articleId:'55',available:true,title:'一起理解 Agent',authorName:'林同学'},status:0,createTime:'2026-10-22T10:01:00'}],
    '203':[{messageId:'3',conversationId:'203',senderId:'9',senderName:'新读者',messageType:1,content:'你好，想讨论文章',status:0,createTime:'2026-10-22T10:02:00'}],'304':[]}
  const state={allow:true,failSend:false,articleAvailable:true,readResult:0}
  const readingProgress={level:0,totalSeconds:0,nextLevel:1,secondsToNext:60,rules:[{level:0,minSeconds:0},{level:1,minSeconds:60}]}
  await page.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname.replace(/^\/api/,''),method=req.method();let data:any=[]
    const body=method==='GET'?{}:req.postDataJSON()||{}
    if(path==='/social/relationships')data=people.filter(p=>(url.searchParams.get('ids')||'').split(',').includes(p.userId))
    else if(/^\/social\/relationships\/\d+\/follow$/.test(path)){const person=people.find(p=>p.userId===path.split('/')[3]);person.isFollowing=body.following;person.isFriend=person.isFollowing&&person.isFollowedBy;data=person}
    else if(/^\/social\/relationships\/\d+\/remark$/.test(path)){const person=people.find(p=>p.userId===path.split('/')[3]);person.remark=body.remark;normal.remark=body.remark;data=person}
    else if(/^\/social\/relationships\/\d+\/block$/.test(path)){const person=people.find(p=>p.userId===path.split('/')[3]);person.isBlockedByMe=body.blocked;person.isFollowing=false;person.isFollowedBy=false;person.isFriend=false;normal.isBlockedByMe=body.blocked;normal.canMessage=!body.blocked;normal.canSendRich=!body.blocked;data=person}
    else if(path==='/social/contacts'){const q=url.searchParams.get('q')||'',blocked=url.searchParams.get('kind')==='blocked';const records=people.filter(p=>(blocked?p.isBlockedByMe:p.isFriend)&&`${p.nickName}${p.remark}`.includes(q));data={records,total:records.length,pages:1}}
    else if(path==='/social/settings'){if(method==='PUT')state.allow=body.allowMessageRequests;data={allowMessageRequests:state.allow}}
    else if(path==='/social/summary')data={messageUnread:normal.isMuted?0:normal.unreadCount,requestPending:incoming.requestState==='PENDING'?1:0,requestUnseen:incoming.requestState==='PENDING'&&incoming.requestUnseen?1:0}
    else if(path==='/social/requests')data=incoming.requestState==='PENDING'?[incoming]:[]
    else if(/^\/social\/requests\/\d+\//.test(path)){const action=path.split('/').at(-1);incoming.requestUnseen=false;if(action==='accept'){incoming.requestState='ACCEPTED';incoming.sendReason=''}if(action==='decline')incoming.requestState='DECLINED';data=incoming}
    else if(/^\/social\/conversations\/\d+\/preferences$/.test(path)){Object.assign(normal,body);data=normal}
    else if(/^\/social\/conversations\/\d+$/.test(path))data=conversations.find(c=>c.conversationId===path.split('/').at(-1))
    else if(/^\/social\/articles\//.test(path))data={articleId:'55',available:state.articleAvailable,title:'一起理解 Agent',authorName:'林同学'}
    else if(path==='/chat/conversations')data=conversations.filter(c=>(c===normal||c.requestState!=='NONE')&&!(c.requestIncoming&&c.requestState!=='ACCEPTED'))
    else if(path==='/chat/conversation/create')data=conversations.find(c=>c.otherUserId===body.targetUserId)
    else if(path==='/chat/message/send'){
      sends.push(body)
      if(state.failSend){state.failSend=false;await route.fulfill({status:503,json:{code:503,message:'发送暂时失败，请重试'}});return}
      const conv=conversations.find(c=>c.conversationId===body.conversationId)!
      data={...body,messageId:String(100+sends.length),senderId:'7',senderName:'我',status:0,createTime:'2026-10-22T10:03:00'}
      if(body.replyToMessageId){const original=rows[conv.conversationId].find(m=>m.messageId===body.replyToMessageId);Object.assign(data,{replyToContent:original.content,replyToSenderName:original.senderName,replyToStatus:original.status})}
      if(body.messageType===3)data.article={articleId:body.articleId,available:true,title:'一起理解 Agent',authorName:'林同学'}
      rows[conv.conversationId].push(data)
      if(conv===stranger){conv.requestState='PENDING';conv.canMessage=false;conv.sendReason='等待对方接受消息请求'}
    }
    else if(path==='/chat/messages')data={records:[...(rows[url.searchParams.get('conversationId')||'']||[])].reverse(),hasMore:false}
    else if(path==='/chat/messages/after')data={records:[],hasMore:false}
    else if(path==='/chat/message/0/context')data={records:[{messageId:'0',conversationId:'101',senderId:'8',senderName:'林同学',messageType:1,content:'较早的原消息',status:0,createTime:'2026-10-21T10:00:00'},...rows['101']],hasMore:true}
    else if(path==='/search'||path==='/search/users')data={records:[people[1]],total:1,pages:1}
    else if(path==='/user/7/followers')data={records:[people[1]],total:1,pages:1}
    else if(path==='/user/7/following')data={records:[people[0]],total:1,pages:1}
    else if(path==='/article/detail/55')data={articleId:'55',title:'一起理解 Agent',authorName:'林同学',userId:'8',authorId:'8',content:'<h2>公开内容</h2><p>一起讨论文章。</p>',canReadFull:true,status:1,requiredLevel:0,tags:[]}
    else if(path==='/share/record'){shareRecords.push(body);data=shareRecords.length}
    else if(path==='/comment/list')data={records:[],total:0,pages:1}
    else if(/\/chat\/conversation\/\d+\/read$/.test(path)){reads.push(body);normal.unreadCount=state.readResult;data={unreadCount:state.readResult,lastReadMessageId:body.lastReadMessageId}}
    else if(path.endsWith('/unread-count')||path.endsWith('/total-unread-count'))data=0
    else if(path.startsWith('/reading/'))data={...readingProgress,sessionId:'reading-test'}
    else if(path.startsWith('/user/space/'))data={userId:path.split('/').at(-1),nickName:'林同学',role:1,status:1,followerCount:3,followingCount:2,readingProgress}
    else if(path.startsWith('/user/')&&path.endsWith('/follow-status'))data=people[0]
    else if(path==='/article/user/8')data={records:[],total:0,pages:1}
    await route.fulfill({json:{code:200,data}})
  })
  return {errors,sockets,sends,reads,shareRecords,state,normal,incoming,people,rows}
}

test('friends use remark search, open the same chat and share one socket with navigation',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?tab=friends')
  await expect(page.getByRole('button',{name:/老同学/})).toBeVisible()
  await page.getByRole('textbox',{name:'搜索联系人或会话'}).fill('老同学')
  await page.getByRole('button',{name:/老同学/}).click()
  await expect(page.locator('.chat-user-name')).toHaveText('老同学')
  await expect(page.getByRole('button',{name:'分享文章',exact:true})).toHaveCount(0)
  await expect(page.getByRole('link',{name:'一起理解 Agent 林同学 · 文章'})).toBeVisible()
  await expect.poll(()=>f.sockets.length).toBe(1)
  await page.screenshot({path:'../artifacts/friends-chat-desktop.png',animations:'disabled'})
  expect(f.errors).toEqual([])
})

test('viewing a request does not accept it; acceptance preserves its greeting and does not follow',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?tab=requests')
  await page.getByRole('button',{name:/新读者/}).click()
  await expect(page.getByText('这是一条消息请求，查看不会自动接受。')).toBeVisible()
  expect(f.incoming.requestState).toBe('PENDING');expect(f.incoming.requestUnseen).toBe(false)
  await page.getByRole('button',{name:'接受',exact:true}).click()
  await expect(page.locator('.chat-request-banner')).toHaveCount(0)
  await expect(page.getByText('你好，想讨论文章',{exact:true}).last()).toBeVisible()
  expect(f.people[1].isFollowing).toBe(false);expect(f.incoming.requestState).toBe('ACCEPTED')
  expect(f.errors).toEqual([])
})

test('rejecting requests and changing request privacy are separate from follow relationships',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?tab=requests');await page.getByRole('button',{name:/新读者/}).click();await page.getByRole('button',{name:'拒绝',exact:true}).click();await expect(page.getByText('暂无消息请求')).toBeVisible();expect(f.incoming.requestState).toBe('DECLINED')
  await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByLabel('接收陌生人的消息请求').uncheck();await expect.poll(()=>f.state.allow).toBe(false);expect(f.people[1].isFollowing).toBe(false);expect(f.errors).toEqual([])
})

test('sending one greeting disables further sends and rich attachments while pending',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?userId=10');await expect(page.getByRole('button',{name:'分享文章',exact:true})).toHaveCount(0);await expect(page.locator('input[type=file]')).toBeDisabled();await page.getByPlaceholder('输入消息...').fill('你好，想交流文章');await page.getByPlaceholder('输入消息...').press('Enter');await expect(page.getByText('等待对方接受消息请求',{exact:true})).toBeVisible();await expect(page.locator('.input-wrapper textarea')).toBeDisabled();expect(f.sends).toHaveLength(1);expect(f.errors).toEqual([])
})

test('conversation preferences and private remarks update the visible session',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?userId=8');await page.getByLabel('会话设置').click();await page.getByRole('button',{name:'置顶会话',exact:true}).click();await expect.poll(()=>f.normal.isTop).toBe(true);await page.getByRole('button',{name:'消息免打扰',exact:true}).click();await expect.poll(()=>f.normal.isMuted).toBe(true)
  await page.getByRole('button',{name:'设置备注',exact:true}).click();const dialog=page.getByRole('dialog',{name:'设置备注'});await dialog.locator('input').fill('一起写作的朋友');await dialog.getByRole('button',{name:'保存',exact:true}).click();await expect(page.locator('.chat-user-name')).toHaveText('一起写作的朋友');expect(f.errors).toEqual([])
})

test('article share retries retain the idempotency key and send only an article ID',async({page})=>{
  const f=await fixture(page);await page.goto('/article/55');await page.getByRole('button',{name:'分享文章',exact:true}).click();const dialog=page.getByRole('dialog',{name:'分享文章',exact:true});await expect(dialog.getByText('一起理解 Agent')).toBeVisible();await dialog.getByRole('radio').check();f.state.failSend=true;await dialog.getByRole('button',{name:'发送给老同学'}).click();await expect(dialog.getByRole('alert')).toBeVisible();expect(f.shareRecords).toHaveLength(0);await dialog.getByRole('button',{name:'发送给老同学'}).click();await expect(dialog).toHaveCount(0);expect(f.sends).toHaveLength(2);expect(f.sends[0].clientMessageId).toBe(f.sends[1].clientMessageId);expect(f.sends[1]).toMatchObject({messageType:3,articleId:'55'});expect(f.sends[1]).not.toHaveProperty('title');await expect.poll(()=>f.shareRecords.length).toBe(1);expect(f.shareRecords[0]).toEqual({articleId:'55',shareType:3});expect(f.errors).toEqual([])
})

test('quoted reply submits the original message ID and a recall updates its preview',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?userId=8');await page.locator('[data-virtual-key="1"]').getByRole('button',{name:'回复',exact:true}).click();await expect(page.locator('.reply-draft')).toContainText('这篇文章可以一起讨论');await page.getByPlaceholder('输入消息...').fill('我们接着讨论');await page.getByPlaceholder('输入消息...').press('Enter');await expect.poll(()=>f.sends.length).toBe(1);expect(f.sends[0].replyToMessageId).toBe('1');await expect(page.locator('.message-quote')).toContainText('这篇文章可以一起讨论');await expect.poll(()=>f.sockets.length).toBe(1);f.sockets[0].send(JSON.stringify({type:'recall',messageId:'1',conversationId:'101',senderId:'8'}));await expect(page.locator('.message-quote')).toContainText('原消息已撤回');expect(f.errors).toEqual([])
})

test('read requests carry the displayed cursor and keep server-reported newer unread',async({page})=>{
  const f=await fixture(page);f.state.readResult=1;await page.goto('/chat?userId=8');await page.locator('.input-wrapper textarea').click();await expect.poll(()=>f.reads.length).toBeGreaterThan(0);expect(f.reads.at(-1)).toEqual({lastReadMessageId:'2'});await expect(page.locator('.social-unread').first()).toHaveText('1');expect(f.errors).toEqual([])
})

test('mobile friend navigation preserves the list search and avoids horizontal overflow',async({page})=>{
  const f=await fixture(page);await page.setViewportSize({width:390,height:844});await page.goto('/chat?tab=friends');await page.getByRole('textbox',{name:'搜索联系人或会话'}).fill('同学');await page.getByRole('button',{name:/老同学/}).click();await expect(page.locator('.chat-user-name')).toBeVisible();await page.locator('.mobile-back-btn').click();await expect(page.getByRole('textbox',{name:'搜索联系人或会话'})).toHaveValue('同学');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:'../artifacts/friends-chat-mobile.png',animations:'disabled'});expect(f.errors).toEqual([])
})

test('search and follower pages share the follow-back and mutual-friend states',async({page})=>{
  const f=await fixture(page);await page.goto('/search?keyword=读者&type=user');await expect(page.getByRole('button',{name:'回关',exact:true})).toBeVisible();await page.getByRole('button',{name:'回关',exact:true}).click();await expect(page.getByRole('button',{name:'互相关注',exact:true})).toBeVisible();expect(f.people[1].isFriend).toBe(true)
  await expect(page.getByLabel('关注关系选项')).toHaveCount(0);await page.getByRole('button',{name:'互相关注',exact:true}).click();const confirm=page.getByRole('dialog',{name:'取消关注'});await expect(confirm).toBeVisible();expect(f.people[1].isFollowing).toBe(true);await confirm.getByRole('button',{name:'取消',exact:true}).click();expect(f.people[1].isFollowing).toBe(true);await expect(page.getByRole('button',{name:'互相关注',exact:true})).toBeVisible();await page.getByRole('button',{name:'互相关注',exact:true}).click();await confirm.getByRole('button',{name:'确定',exact:true}).click();await expect(page.getByRole('button',{name:'回关',exact:true})).toBeVisible();expect(f.people[1].isFollowing).toBe(false);await page.getByRole('button',{name:'回关',exact:true}).click();await expect(page.getByRole('button',{name:'互相关注',exact:true})).toBeVisible()
  await page.goto('/followers-following?userId=7&tab=followers');await expect(page.getByRole('button',{name:'互相关注',exact:true})).toBeVisible();await page.getByRole('button',{name:'朋友 · 互相关注'}).click();await expect(page.locator('.user-list')).toContainText('新读者');expect(f.errors).toEqual([])
})

test('article share opens a friend picker, keeps copy link optional and fits mobile',async({page,context})=>{
  await context.grantPermissions(['clipboard-read','clipboard-write'])
  const f=await fixture(page);f.people[1].isFriend=true
  await page.goto('/article/55');await page.evaluate(()=>navigator.clipboard.writeText('尚未分享'))
  await page.getByRole('button',{name:'分享文章',exact:true}).click()
  await expect(page.getByRole('button',{name:'分享文章',exact:true})).toHaveAttribute('aria-expanded','true')
  const dialog=page.getByRole('dialog',{name:'分享文章',exact:true})
  await expect(dialog.getByText('一起理解 Agent')).toBeVisible();await expect(dialog.getByLabel('文章链接或 ID')).toHaveCount(0)
  expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe('尚未分享');expect(f.sends).toHaveLength(0);expect(f.shareRecords).toHaveLength(0)
  await dialog.getByRole('button',{name:'复制链接',exact:true}).click()
  await expect.poll(()=>f.shareRecords.length).toBe(1);expect(f.shareRecords[0]).toEqual({articleId:'55',shareType:0})
  expect(await page.evaluate(()=>navigator.clipboard.readText())).toMatch(/\/article\/55$/)
  await dialog.getByRole('radio').first().check();await page.screenshot({path:'../artifacts/article-share-desktop.png',animations:'disabled'})
  await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
  await page.screenshot({path:'../artifacts/article-share-mobile.png',animations:'disabled'})
  await dialog.getByRole('button',{name:'发送给老同学'}).click();await expect(dialog).toHaveCount(0)
  expect(f.sends[0]).toMatchObject({messageType:3,articleId:'55'});await expect.poll(()=>f.shareRecords.length).toBe(2);expect(f.shareRecords[1]).toEqual({articleId:'55',shareType:3});expect(f.errors).toEqual([])
})

test('blocking clears friendship without deleting history; unblocking does not follow again',async({page})=>{
  const f=await fixture(page);await page.goto('/chat?userId=8');await page.getByLabel('会话设置').click();await page.getByRole('button',{name:'拉黑用户',exact:true}).click();await page.getByRole('dialog',{name:'拉黑用户'}).getByRole('button',{name:'拉黑',exact:true}).click();await expect(page.locator('.input-wrapper textarea')).toBeDisabled();await expect(page.getByRole('button',{name:'已拉黑',exact:true})).toBeVisible();await expect(page.getByRole('link',{name:'一起理解 Agent 林同学 · 文章'})).toBeVisible();expect(f.people[0].isFriend).toBe(false);await page.getByRole('button',{name:'解除拉黑',exact:true}).click();await expect(page.getByRole('button',{name:'关注',exact:true})).toBeVisible();expect(f.people[0].isFollowing).toBe(false);expect(f.errors).toEqual([])
})

test('a quote can load an older original and return to the latest messages',async({page})=>{
  const f=await fixture(page);f.rows['101'].push({messageId:'4',conversationId:'101',senderId:'8',senderName:'林同学',messageType:1,content:'继续之前的话题',replyToMessageId:'0',replyToSenderName:'林同学',replyToContent:'较早的原消息',status:0,createTime:'2026-10-22T10:02:00'});await page.goto('/chat?userId=8');await page.locator('.message-quote').click();await expect(page.locator('[data-virtual-key="0"]')).toContainText('较早的原消息');await expect(page.getByRole('button',{name:'返回最新消息',exact:true})).toBeVisible();await page.getByRole('button',{name:'返回最新消息',exact:true}).click();await expect(page.getByRole('button',{name:'返回最新消息',exact:true})).toHaveCount(0);await expect(page.locator('[data-virtual-key="4"]')).toBeVisible();await expect(page.locator('[data-virtual-key="0"]')).toHaveCount(0);expect(f.errors).toEqual([])
})
