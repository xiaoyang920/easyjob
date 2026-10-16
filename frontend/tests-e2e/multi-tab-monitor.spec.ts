import {test,expect} from '@playwright/test'

for(const tabCount of [2,6]) test(`${tabCount} tabs consume shared run snapshots without recursively refetching`,async({context})=>{
  await context.addInitScript(()=>{localStorage.setItem('token',`qa.${btoa(JSON.stringify({userId:7,exp:Math.floor(Date.now()/1000)+3600}))}.test`);localStorage.setItem('userId','7')})
  let polls=0
  await context.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;let data:any=[]
    if(path.endsWith('/agent/run-overview'))data={items:[],serverTime:new Date(Date.now()+polls++).toISOString()}
    else if(path.endsWith('/notification/stream'))return route.fulfill({contentType:'text/event-stream',body:'event: connected\ndata: ok\n\n'})
    else if(path.endsWith('/user/space/7'))data={role:1,status:1,nickName:'多标签页测试'}
    else if(path.endsWith('/unread-count'))data=0
    await route.fulfill({json:{code:200,data}})
  })
  const pages=await Promise.all(Array.from({length:tabCount},()=>context.newPage()))
  const [first,second]=pages
  await Promise.all(pages.map(page=>page.goto('/account-security')))
  await expect.poll(()=>polls).toBeGreaterThanOrEqual(tabCount)
  await second.waitForTimeout(1500)
  expect(polls).toBeLessThan(tabCount*3)
  const before=polls
  await first.evaluate(()=>{for(let i=0;i<100;i++)localStorage.setItem('ai_run_notices:7',JSON.stringify({syncedAt:new Date(Date.now()+i+1000).toISOString(),items:[{runId:'completed-run',conversationId:'101',title:'来自另一页',status:'succeeded',updatedAt:new Date().toISOString(),unread:true}]}))})
  for(const page of pages.slice(1))await expect(page.locator('.app-nav-link').filter({hasText:'AI'}).locator('.app-nav-badge')).toHaveText('1')
  await second.waitForTimeout(1000)
  expect(polls).toBe(before)
})
