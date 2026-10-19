import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import { JSDOM } from 'jsdom'
import { restoreAgentState } from '../src/utils/agentStream.ts'
import { approvalRecovery } from '../src/utils/approvalRecovery.ts'

test('real activity panel shows incomplete delivery after reload while retaining completed retrieval', async () => {
  const dom = new JSDOM('<div id="root"></div>', { pretendToBeVisual: true })
  for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'Node']) globalThis[key] = dom.window[key]
  const vue = await import('vue')
  const source = (await readFile(new URL('../src/components/AgentActivity.vue', import.meta.url), 'utf8'))
    .replace(/import type \{ AgentStreamState \} from '[^']+'/, 'type AgentStreamState = Record<string, any>')
  const { descriptor } = parse(source)
  const script = compileScript(descriptor, { id: 'incomplete-qa', inlineTemplate: true }).content
  const modulePath = fileURLToPath(new URL(`.agent-incomplete-${process.pid}.mjs`, import.meta.url))
  let app
  try {
    await writeFile(modulePath, ts.transpileModule(script, { compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText)
    const component = (await import(pathToFileURL(modulePath).href)).default
    const state = restoreAgentState({ runStatus: 'succeeded', deliveryStatus: 'incomplete', agentEvents: [
      { version: 1, kind: 'activity', id: 'lookup', label: '检索相关资料', status: 'done' }] })
    app = vue.createApp(component, { state })
    app.mount('#root')
    assert.equal(document.querySelector('.activity-summary').textContent, '处理未完成')
    assert.equal(document.querySelector('.status-indicator').textContent, '!')
    assert.equal(document.querySelector('.activity-item .item-mark').textContent, '✓')
    assert.equal(document.querySelector('.item-title').textContent.trim(), '检索相关资料')
  } finally {
    app?.unmount()
    await unlink(modulePath).catch(() => {})
    dom.window.close()
  }
})

test('reconciliation distinguishes incomplete delivery while committed draft still wins', () => {
  assert.equal(approvalRecovery({ status: 'succeeded', result: { delivery_status: 'incomplete' } }).status, 'error')
  assert.equal(approvalRecovery({ status: 'succeeded', draftArticleId: '42', result: { delivery_status: 'incomplete' } }).status, 'complete')
})
