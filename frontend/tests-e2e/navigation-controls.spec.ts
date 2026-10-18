import { test, expect, type Page, type Locator } from '@playwright/test'

const selectRoot=(control:Locator)=>control.locator('xpath=ancestor::div[contains(concat(" ",normalize-space(@class)," ")," ej-select ")][1]')

async function fixture(page:Page, own=false) {
  await page.setViewportSize({width:1440,height:900})
  await page.emulateMedia({reducedMotion:'reduce'})
  await page.addInitScript(()=>{
    localStorage.setItem('token',`qa.${btoa(JSON.stringify({sub:'7',exp:Math.floor(Date.now()/1000)+3600}))}.test`)
    localStorage.setItem('userId','7');localStorage.setItem('nickName','验收用户')
  })
  const errors:string[]=[], writes:any[]=[], searches:URL[]=[]
  page.on('pageerror',e=>errors.push(e.message))
  const user={userId:own?'7':'8',nickName:'示例用户',role:1,status:1,personIntroduction:'技术博客读者',readingSeconds:0,readingMillis:'0',readingLevel:0,rules:[{level:0,minSeconds:0}]}
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();let data:any=[]
    if(method==='PUT'){writes.push(route.request().postDataJSON());data=true}
    else if(path.endsWith('/admin/me'))data={userId:'7',permissions:['overview.read','users.read','users.write','articles.read','categories.read','metrics.read']}
    else if(path.endsWith('/admin/overview'))data={users:1,published:0,readingSeconds:0,rules:user.rules}
    else if(path.endsWith('/admin/users'))data={records:[user],total:1,pages:1}
    else if(/\/admin\/users\/\d+$/.test(path))data=user
    else if(path.endsWith('/user/space/7'))data={userId:'7',nickName:'验收用户',role:2,status:1,sex:2,theme:1}
    else if(path.endsWith('/agent/library'))data={rows:url.searchParams.get('scope')==='general'?[{conversationId:'101',title:'反馈验收'}]:[],total:1}
    else if(path.endsWith('/agent/conversations/101'))data={conversationId:'101',title:'反馈验收'}
    else if(path.endsWith('/messages'))data=[{role:'assistant',content:'这是用于界面验证的示例回答。',runId:'01b3e467-9daa-4ad1-b1cc-5ccfe70e38de'}]
    else if(path.endsWith('/questions'))data={items:[],hasMore:false}
    else if(path.endsWith('/feedback')||path.endsWith('/run'))data=null
    else if(path.endsWith('/agent/run-overview'))data={items:[]}
    else if(path==='/api/search'){searches.push(url);data={records:[],total:0,pages:1}}
    else if(path.endsWith('/unread-count')||path.endsWith('/total-unread-count'))data=0
    await route.fulfill({json:{code:200,data}})
  })
  return {errors,writes,searches}
}

test('admin dialog covers navigation, keeps title/actions in view and saves numeric choices',async({page})=>{
  const {errors,writes}=await fixture(page)
  await page.goto('/admin?section=users');await page.getByRole('button',{name:'编辑',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'编辑用户'})
  await expect(dialog.getByText('编辑用户',{exact:true})).toBeVisible()
  expect(await dialog.evaluate(el=>el.closest('#app'))).toBeNull()
  expect(await page.evaluate(()=>!!document.elementFromPoint(25,30)?.closest('.el-overlay'))).toBe(true)
  const role=dialog.getByRole('combobox',{name:'角色',exact:true})
  await role.click();await page.getByRole('option',{name:'运营员',exact:true}).click()
  await expect(selectRoot(role)).toContainText('运营员')
  await dialog.getByRole('combobox',{name:'账号状态',exact:true}).click()
  await page.getByRole('option',{name:'禁用',exact:true}).click()
  await dialog.getByLabel('修改原因',{exact:true}).fill('界面回归夹具')
  await page.screenshot({path:'../logs/admin-dialog-controls-desktop.png',animations:'disabled'})
  await dialog.getByRole('button',{name:'保存修改',exact:true}).click()
  await expect(dialog).toHaveCount(0)
  expect(writes.at(-1)).toMatchObject({role:4,status:0})
  expect(errors).toEqual([])
})

test('long admin form scrolls inside the modal on a narrow screen and self-role stays protected',async({page})=>{
  const {errors}=await fixture(page,true);await page.setViewportSize({width:390,height:640})
  await page.goto('/admin?section=users');await page.getByRole('button',{name:'编辑',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'编辑用户'})
  await expect(dialog.getByRole('combobox',{name:'角色',exact:true})).toBeDisabled()
  await expect(dialog.getByRole('combobox',{name:'账号状态',exact:true})).toBeDisabled()
  await expect(dialog.getByText('编辑用户',{exact:true})).toBeInViewport()
  await expect(dialog.getByRole('button',{name:'取消',exact:true})).toBeInViewport()
  await expect.poll(async()=>Math.round((await dialog.boundingBox())!.y)).toBeGreaterThanOrEqual(0);const box=(await dialog.boundingBox())!;expect(box.y+box.height).toBeLessThanOrEqual(640)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
  await page.screenshot({path:'../logs/admin-dialog-controls-mobile.png',animations:'disabled'})
  await dialog.getByRole('button',{name:'取消',exact:true}).click();await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('link',{name:'EasyJob 首页',exact:true})).toBeVisible()
  expect(errors).toEqual([])
})

test('answer feedback uses the paper dropdown and keyboard selection preserves submitted reason',async({page})=>{
  const {errors,writes}=await fixture(page)
  await page.goto('/ai-chat?conversationId=101');await page.getByRole('button',{name:'有问题',exact:true}).click()
  const reason=page.getByRole('combobox',{name:'问题类型',exact:true})
  await reason.click()
  const menu=page.locator('.el-popper.ej-select-menu:visible')
  await expect(menu).toHaveCSS('background-color','rgb(255, 253, 247)')
  await expect(menu.getByRole('option',{name:'事实或推理错误',exact:true})).toHaveCSS('background-color','rgb(233, 255, 179)')
  await page.screenshot({path:'../logs/answer-feedback-dropdown.png',animations:'disabled'})
  await page.keyboard.press('Escape');await expect(reason).toHaveAttribute('aria-expanded','false')
  await reason.focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter')
  await expect(selectRoot(reason)).toContainText('引用有误')
  await page.getByRole('button',{name:'提交反馈',exact:true}).click()
  await expect(page.getByRole('status').filter({hasText:'感谢反馈'})).toBeVisible()
  expect(writes.at(-1)).toMatchObject({rating:'problem',reason:'citation'})
  expect(errors).toEqual([])
})

test('empty string remains a valid filter option and sort changes still send the original value',async({page})=>{
  const {errors,searches}=await fixture(page)
  await page.goto('/search?keyword=缓存')
  const sort=page.getByRole('combobox',{name:'排序方式',exact:true})
  await expect(selectRoot(sort)).toContainText('相关度')
  await sort.click();await page.getByRole('option',{name:'最多收藏',exact:true}).click()
  await expect.poll(()=>searches.at(-1)?.searchParams.get('orderType')).toBe('3')
  await sort.click();await page.getByRole('option',{name:'相关度',exact:true}).click()
  await expect.poll(()=>searches.at(-1)?.searchParams.has('orderType')).toBe(false)
  expect(errors).toEqual([])
})
