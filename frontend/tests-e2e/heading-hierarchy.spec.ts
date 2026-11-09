import { test, expect, type Page } from '@playwright/test'

const headings = Array.from({ length: 6 }, (_, index) => `<h${index + 1}>第${index + 1}级标题，较长的标题换行后也应保持相同的左边界</h${index + 1}>`).join('')
async function open(page: Page, reading = false) {
  await page.addInitScript(() => {
    localStorage.setItem('userId', '7')
    localStorage.setItem('token', `qa.${btoa(JSON.stringify({sub:'7',exp:Date.now()/1000+3600}))}.headings`)
  })
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    let data: any = []
    if (path.endsWith('/article/42/edit')) data = {articleId:'42',title:'标题层级',content:headings + '<p style="text-indent:2em;">待转换的正文</p>',status:0,revisionId:'r1',lockVersion:1}
    else if (path.endsWith('/article/detail/42')) data = {articleId:'42',title:'标题层级',content:headings,canReadFull:true,authorId:'7',authorName:'示例作者',tags:[]}
    else if (path.endsWith('/agent/run-overview')) data = {items:[]}
    else if (path.includes('unread-count')) data = 0
    else if (path.includes('/comment/')) data = {records:[],total:0,pages:1,nextCursor:''}
    else if (path.startsWith('/api/reading/')) data = {sessionId:'qa',sessionToken:'qa',level:0,totalSeconds:0,rules:[]}
    return route.fulfill({json:{code:200,data}})
  })
  await page.goto(reading ? '/article/42' : '/edit-article?id=42')
  if (!reading) await expect(page.locator('.editor-action-bar .writing-ai-trigger')).toBeEnabled()
  const root = page.locator(reading ? '.article-content' : '[data-slate-editor]')
  await expect(root.locator('h1')).toContainText('第1级标题')
  return root
}

for (const width of [1440, 390]) {
  for (const reading of [false, true]) {
    test(`headings stay flush without automatic level offsets in ${reading ? 'reading' : 'editing'} at ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({width,height:1000})
      const root = await open(page, reading)
      // wangEditor offers H1–H5. The reader also retains imported H6.
      const levels = reading ? 6 : 5
      for (let level = 1; level <= levels; level++) {
        await expect(root.locator(`h${level}`)).toHaveCSS('margin-inline-start', '0px')
      }
      expect(await root.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      if (!reading) {
        await page.locator('.toolbar [data-menu-key="fullScreen"]').click()
        for (let level = 1; level <= levels; level++) {
          await expect(root.locator(`h${level}`)).toHaveCSS('margin-inline-start', '0px')
        }
      }
      await page.screenshot({path:info.outputPath(`heading-${reading ? 'reader' : 'editor'}-${width}.png`)})
    })
  }
}

test('changing an indented paragraph to a heading preserves the author chosen indent', async ({ page }) => {
  const root = await open(page)
  await root.locator('p').filter({hasText:'待转换的正文'}).click()
  await page.locator('.toolbar [data-menu-key="articleBlockStyle"]').click()
  await page.locator('.w-e-select-list:visible li[data-value="header3"]').click()
  const heading = root.locator('h3').filter({hasText:'待转换的正文'})
  await expect(heading).toHaveCSS('text-indent','32px')
  await expect(heading).toHaveCSS('margin-inline-start','0px')
  await page.keyboard.press('Control+z')
  await expect(root.locator('p').filter({hasText:'待转换的正文'})).toHaveCSS('text-indent','32px')
})
