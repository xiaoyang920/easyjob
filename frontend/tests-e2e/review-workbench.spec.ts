import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

// Synthetic UI fixture only; these labels never enter the real evaluation output.
test('offline review requires explicit labels and rejects stale imports', async ({ page }) => {
  const template = await readFile('../python-agent/evaluation/review_workbench.html', 'utf8')
  const bundle = { mode:'live', expected:1, hash:'ui-test-only', items:[{
    id:'ui-fixture-only', category:'UI contract', query:'仅供界面回归的合成问题', sources:[{content:'<script>window.injected=true</script>'}],
    candidate:'合成候选', final:'合成回答', candidate_hash:'candidate-fixture', final_hash:'final-fixture', audit:{},
  }] }
  const payload = JSON.stringify(bundle).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e')
  await page.route('**/review-fixture.html', route => route.fulfill({contentType:'text/html',body:template.replace('__EVALUATION_BUNDLE__',payload)}))
  await page.goto('/review-fixture.html')
  await expect(page.locator('#progress')).toContainText('已标注 0/1')
  await expect(page.locator('[name=task_completed]')).toHaveValue('')
  await expect(page.locator('[name=specific_facts]')).toHaveValue('')
  await page.locator('#export').click(); await expect(page.locator('#notice')).toContainText('至少一题')
  await page.locator('summary').first().click()
  await expect(page.locator('#sources')).toContainText('<script>')
  expect(await page.evaluate(() => (window as any).injected)).toBeUndefined()
  await page.locator('#reviewer').fill('synthetic-ui-tester')
  await page.locator('[name=task_completed]').selectOption('true')
  await page.locator('[name=context_coherent]').selectOption('true')
  for (const [name,value] of Object.entries({candidate_correct_units:'2',falsely_blocked_units:'0',specific_facts:'1',unsupported_specific_facts:'0'})) await page.locator(`[name=${name}]`).fill(value)
  await page.locator('#attest').check(); await page.getByRole('button',{name:'保存本题标注'}).click()
  await expect(page.locator('#progress')).toContainText('已标注 1/1')
  const [download] = await Promise.all([page.waitForEvent('download'),page.locator('#export').click()])
  const exported = JSON.parse((await readFile((await download.path())!,'utf8')).trim())
  expect(exported.id).toBe('ui-fixture-only'); expect(exported.assessor).toBe('human')
  await page.locator('#import').setInputFiles({name:'stale.jsonl',mimeType:'application/x-ndjson',buffer:Buffer.from(JSON.stringify({...exported,final_hash:'changed'}))})
  await expect(page.locator('#notice')).toContainText('过期标签')
  await expect(page.locator('#progress')).toContainText('已标注 1/1')
  await page.screenshot({path:'../logs/review-workbench-preview.png',animations:'disabled'})
})
