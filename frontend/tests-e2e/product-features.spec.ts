import {test,expect,type Page} from '@playwright/test'
async function identity(page:Page){
 await page.addInitScript(()=>{localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600}))}.test`);localStorage.setItem('userId','7')})
 page.on('dialog',d=>void d.accept())
}
async function editor(page:Page,save:(r:any)=>Promise<void>){
 await identity(page)
 await page.route('**/api/**',async r=>{
  const path=new URL(r.request().url()).pathname;let data:any=[]
  if(path==='/api/article/42' && r.request().method()==='PUT')return save(r)
  if(path.endsWith('/article/42/edit'))data={articleId:'42',title:'原始标题',categoryId:1,content:'<p>原始正文</p>',revisionId:'10',lockVersion:0,revisionState:0,status:0,tags:[]}
  else if(path.endsWith('/category/list'))data=[{categoryId:1,categoryName:'测试'}]
  else if(path.endsWith('/user/space/7'))data={role:1,status:1}
  else if(path.endsWith('/agent/run-overview'))data={items:[]}
  await r.fulfill({json:{code:200,data}})
 })
 await page.goto('/create-article?id=42');await expect(page.getByPlaceholder('请输入文章标题...')).toHaveValue('原始标题')
}
test('autosave preserves edits made while the previous save is waiting and reuses revision',async({page})=>{
 const saves:any[]=[];let release!:()=>void;const gate=new Promise<void>(r=>release=r)
 await editor(page,async r=>{saves.push(r.request().postDataJSON());if(saves.length===1)await gate;await r.fulfill({json:{code:200,data:{articleId:'42',revisionId:'10',lockVersion:saves.length,revisionState:0}}})})
 await page.getByPlaceholder('请输入文章标题...').fill('第一次修改')
 await expect.poll(()=>saves.length,{timeout:10000}).toBe(1)
 await page.getByPlaceholder('请输入文章标题...').fill('保存期间继续输入')
 release();await expect(page.getByPlaceholder('请输入文章标题...')).toHaveValue('保存期间继续输入')
 await expect.poll(()=>saves.length,{timeout:12000}).toBe(2)
 expect(saves.map(v=>v.expectedRevisionId)).toEqual(['10','10']);expect(saves[1].expectedLockVersion).toBe(1);expect(saves.every(v=>v.status===0)).toBe(true)
 await expect(page.locator('.autosave-status')).toContainText('草稿已保存')
})
test('a conflict pauses autosave and retains a recoverable local copy',async({page})=>{
 let saves=0
 await editor(page,async r=>{saves++;await r.fulfill({status:409,json:{code:409,message:'草稿版本已变化'}})})
 await page.getByPlaceholder('请输入文章标题...').fill('未被覆盖的内容')
 await expect(page.getByText('草稿已在其他页面修改，自动保存已暂停。请先复制保留当前内容，再刷新核对。')).toBeVisible({timeout:10000})
 await page.waitForTimeout(6000);expect(saves).toBe(1)
 await page.reload();await page.getByRole('button',{name:'恢复到编辑器'}).click()
 await expect(page.getByPlaceholder('请输入文章标题...')).toHaveValue('未被覆盖的内容')
})
test('conversation rename, pin, search and feedback persist after refresh',async({page})=>{
 await identity(page);let conv={conversationId:'101',title:'原始会话',metadataVersion:0,isPinned:0},feedback:any=null
 await page.route('**/api/**',async r=>{
  const u=new URL(r.request().url()),path=u.pathname;let data:any=[]
  if(path.endsWith('/agent/library'))data={rows:u.searchParams.get('scope')==='general' && (!u.searchParams.get('keyword') || conv.title.includes(u.searchParams.get('keyword')!))?[conv]:[],total:1}
  else if(path.endsWith('/agent/conversations/101') && r.request().method()==='PATCH'){const edit=r.request().postDataJSON();expect(edit.version).toBe(conv.metadataVersion);conv={...conv,title:edit.title??conv.title,isPinned:edit.pinned===undefined?conv.isPinned:Number(edit.pinned),metadataVersion:conv.metadataVersion+1};data={version:conv.metadataVersion}}
  else if(path.endsWith('/agent/conversations/101'))data=conv
  else if(path.endsWith('/messages'))data=[{role:'assistant',content:'测试回答',runId:'0d326ff2-b461-4eea-9d9d-024f0a45da37'}]
  else if(path.endsWith('/feedback')){if(r.request().method()==='PUT')feedback=r.request().postDataJSON();data=feedback}
  else if(path.endsWith('/run'))data=null
  else if(path.endsWith('/agent/run-overview'))data={items:[]}
  await r.fulfill({json:{code:200,data}})
 })
 await page.goto('/ai-chat?conversationId=101')
 await page.getByRole('button',{name:'重命名对话'}).click();await page.locator('.el-message-box input').fill('缓存问题');await page.locator('.el-message-box').getByRole('button',{name:'保存',exact:true}).click()
 await expect(page.locator('.conv-title')).toContainText('缓存问题');await page.getByRole('button',{name:'置顶对话',exact:true}).click();await expect(page.getByRole('button',{name:'取消置顶',exact:true})).toBeVisible()
 await page.getByRole('button',{name:'有帮助',exact:true}).click();await expect(page.getByRole('button',{name:'✓ 有帮助'})).toBeVisible()
 await page.reload();await expect(page.getByRole('button',{name:'✓ 有帮助'})).toBeVisible()
 await page.getByRole('textbox',{name:'搜索对话'}).fill('不存在');await expect(page.locator('.conversation-item')).toHaveCount(0)
})
test('account page lists devices and revokes other sessions with confirmation',async({page},info)=>{
 await identity(page);let devices=[{id:'a'.repeat(64),current:true,userAgent:'Chrome/130',createdAt:Date.now(),lastSeen:Date.now()},{id:'b'.repeat(64),current:false,userAgent:'Firefox/130',createdAt:Date.now(),lastSeen:Date.now()}]
 await page.route('**/api/**',async r=>{const p=new URL(r.request().url()).pathname;let data:any=[];if(p.endsWith('/account/sessions/revoke-others'))devices=devices.slice(0,1);else if(p.endsWith('/account/sessions'))data=devices;else if(p.endsWith('/agent/run-overview'))data={items:[]};await r.fulfill({json:{code:200,data}})})
 await page.goto('/account-security');await expect(page.locator('.device-row')).toHaveCount(2);await page.screenshot({path:info.outputPath('account-security.png'),fullPage:true,animations:'disabled'})
 await page.getByRole('button',{name:'退出其他设备',exact:true}).click();await page.locator('.el-message-box').getByRole('button',{name:'确定',exact:true}).click();await expect(page.locator('.device-row')).toHaveCount(1)
})

test('revision comparison marks changed text without creating snapshots',async({page},info)=>{
 await identity(page)
 await page.route('**/api/**',async r=>{const p=new URL(r.request().url()).pathname;let data:any=[]
  if(p.endsWith('/article/work'))data={records:[{articleId:'42',title:'对比测试',revisionId:'11',revisionState:0,lockVersion:0,articleStatus:1,updateTime:'2026-10-14T00:00:00'}],total:1}
  else if(p.endsWith('/article/42/revisions'))data=[{revisionId:'11',version:2,state:0},{revisionId:'10',version:1,state:2}]
  else if(p.endsWith('/revisions/11'))data={revisionId:'11',version:2,state:0,payload:{title:'新标题',content:'<p>保留内容</p><p>新增内容</p>',contentType:1}}
  else if(p.endsWith('/revisions/10'))data={revisionId:'10',version:1,state:2,payload:{title:'旧标题',content:'<p>保留内容</p><p>旧段落</p>',contentType:1}}
  else if(p.endsWith('/agent/run-overview'))data={items:[]}
  await r.fulfill({json:{code:200,data}})
 })
 await page.goto('/draft-box');await page.getByRole('button',{name:'版本历史'}).click();await page.getByLabel('对比基准').selectOption('10')
 await expect(page.locator('.revision-comparison .add').filter({hasText:'新增内容'})).toBeVisible();await expect(page.locator('.revision-comparison .remove').filter({hasText:'旧段落'})).toBeVisible();await page.screenshot({path:info.outputPath('revision-comparison.png'),fullPage:true,animations:'disabled'})
})

test('lost first-save response retries the same request and then continues updating one draft',async({page})=>{
 await identity(page);await page.clock.install();const creates:any[]=[],updates:any[]=[]
 await page.route('**/api/**',async r=>{const p=new URL(r.request().url()).pathname;let data:any=[]
  if(p.endsWith('/article/create')){creates.push(r.request().postDataJSON());if(creates.length===1)return r.abort('failed');data={articleId:'999',revisionId:'19',lockVersion:0,revisionState:0}}
  else if(p.endsWith('/article/999') && r.request().method()==='PUT'){updates.push(r.request().postDataJSON());data={articleId:'999',revisionId:'19',lockVersion:1,revisionState:0}}
  else if(p.endsWith('/category/list'))data=[{categoryId:1,categoryName:'测试'}]
  else if(p.endsWith('/agent/run-overview'))data={items:[]}
  await r.fulfill({json:{code:200,data}})
 })
 await page.goto('/create-article');await page.getByPlaceholder('请输入文章标题...').fill('首次保存');await page.locator('.category-select').selectOption('1')
 await page.clock.fastForward(6000);await expect.poll(()=>creates.length).toBe(1);await expect(page.locator('.autosave-status')).toContainText('保存失败')
 await page.clock.fastForward(16000);await expect.poll(()=>creates.length).toBe(2);await expect(page).toHaveURL(/id=999/)
 expect(creates[0].clientRequestId).toBe(creates[1].clientRequestId);expect(creates[0].clientRequestId).toMatch(/^[a-f0-9-]{36}$/)
 await page.getByPlaceholder('请输入文章标题...').fill('接着修改');await page.clock.fastForward(6000);await expect.poll(()=>updates.length).toBe(1)
 expect(updates[0].expectedRevisionId).toBe('19');expect(updates[0].expectedLockVersion).toBe(0)
})
