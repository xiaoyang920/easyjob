import { test,expect,type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
const fixture=JSON.parse(fs.readFileSync(path.resolve('../temp/platform-browser-fixture.json'),'utf8'))
async function login(page:Page,key:string){
 const user=fixture.users.find((u:any)=>u.key===key)
 const response=await page.request.post('/api/auth/login',{data:{email:user.email,password:fixture.password}})
 const body=await response.json();expect(body.code).toBe(200)
 await page.addInitScript(data=>{localStorage.setItem('token',data.token);localStorage.setItem('userId',String(data.userId));localStorage.setItem('nickName',data.nickName || '');localStorage.setItem('email',data.email || '')},body.data)
}
test('administrator exports a real workbook and changes statistical source',async({page},info)=>{
 await login(page,'admin');await page.goto('/admin')
 await expect(page.getByRole('heading',{name:'概览',exact:true})).toBeVisible()
 const scope=page.getByRole('combobox',{name:'统计数据来源'});await expect(page.locator('.statistics-controls > .ej-select')).toContainText('真实业务');await scope.click();await page.getByRole('option',{name:'评测样例',exact:true}).click()
 const button=page.getByRole('button',{name:'导出 Excel',exact:true});await expect(button).toBeEnabled()
 const [download]=await Promise.all([page.waitForEvent('download'),button.click()]);expect(download.suggestedFilename()).toContain('评测样例')
 const filename=info.outputPath('statistics.xlsx');await download.saveAs(filename);expect(fs.readFileSync(filename).subarray(0,2).toString()).toBe('PK')
 await page.getByRole('button',{name:'Agent 指标',exact:false}).click();await expect(page.getByRole('heading',{name:'Agent 指标',exact:true})).toBeVisible()
 await expect(page.getByText('完成成功率',{exact:true})).toBeVisible()
})
test('reviewer sees permitted modules and approves a real submitted revision',async({page})=>{
 await login(page,'reviewer');await page.goto('/admin?section=reviews')
 await expect(page.getByRole('heading',{name:'文章审核',exact:true})).toBeVisible()
 await expect(page.locator('.admin-sidebar').getByRole('button',{name:'用户与成长'})).toHaveCount(0)
 await expect(page.locator('.admin-sidebar').getByRole('button',{name:'分类管理'})).toHaveCount(0)
 const row=page.locator('.review-panel tr').filter({hasText:fixture.marker+'-review'})
 await row.getByRole('button',{name:'查看并审核'}).click();await page.getByRole('button',{name:'通过审核',exact:true}).click()
 await page.locator('.el-message-box').getByRole('button',{name:'确定',exact:true}).click()
 await expect(row).toHaveCount(0)
})
test('operator manages a category but has no user/approval controls',async({page})=>{
 await login(page,'operator');await page.goto('/admin?section=categories')
 await expect(page.getByRole('heading',{name:'分类管理',exact:true})).toBeVisible()
 await expect(page.locator('.admin-sidebar').getByRole('button',{name:'文章审核'})).toHaveCount(0)
 const row=page.locator('.categories-panel tr').filter({hasText:fixture.marker})
 await row.getByRole('button',{name:'编辑',exact:true}).click()
 const dialog=page.getByRole('dialog');await dialog.getByLabel('名称',{exact:true}).fill(fixture.marker+'-renamed');await dialog.getByRole('button',{name:'保存修改'}).click()
 await expect(page.locator('.categories-panel strong').filter({hasText:fixture.marker+'-renamed'})).toBeVisible()
})
test('reader can hide a recommendation and restore it without navigating into the article',async({page})=>{
 await login(page,'reader');await page.goto('/')
 await expect(page.getByRole('button',{name:'推荐偏好',exact:true})).toBeVisible()
 await page.locator('.category-nav').getByRole('button',{name:fixture.marker+'-renamed',exact:true}).click()
 const card=page.locator('.article-card').filter({hasText:fixture.marker+'-article-1'})
 await card.getByRole('button',{name:'调整《'+fixture.marker+'-article-1》的推荐'}).click()
 await page.getByRole('menuitem',{name:'不感兴趣',exact:true}).click();await expect(card).toHaveCount(0);expect(new URL(page.url()).pathname).toBe('/')
 await page.getByRole('button',{name:'推荐偏好',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'恢复推荐',exact:true}).click()
 await expect(page.getByRole('dialog').getByText('暂未隐藏任何推荐')).toBeVisible()
})

test('operator metrics remain usable on a phone without horizontal overflow',async({page},info)=>{
 await page.setViewportSize({width:390,height:844});await login(page,'operator');await page.goto('/admin?section=agentMetrics')
 await expect(page.getByText('完成成功率',{exact:true})).toBeVisible()
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false)
 await page.screenshot({path:info.outputPath('metrics-mobile.png'),fullPage:true})
})
