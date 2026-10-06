import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { pathToFileURL, fileURLToPath } from 'node:url'
import ts from 'typescript'
import { JSDOM } from 'jsdom'

test('global monitor restores runs, retains reconnect state and fences account changes', async()=>{
  const dom=new JSDOM('',{url:'http://localhost'})
  globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.localStorage=dom.window.localStorage
  localStorage.setItem('userId','7');localStorage.setItem('token','qa')
  const run=(status='running',cid='101')=>({runId:'r-'+cid,conversationId:cid,title:'对话'+cid,status,updatedAt:'2026-10-05T11:00:00Z'})
  localStorage.setItem('ai_run_notices:7',JSON.stringify({items:[{...run(),unread:false}],syncedAt:'2026-10-05T10:00:00Z'}))
  let response={code:200,data:{items:[run('succeeded')],serverTime:'2026-10-05T11:01:00Z'}}, deferred=null, calls=0
  globalThis.__runQa={get:async()=>{calls++;if(deferred)return deferred;if(response instanceof Error)throw response;return response}}
  const input=fileURLToPath(new URL('../src/utils/aiRuns.ts',import.meta.url))
  let source=await readFile(input,'utf8')
  source=source.replace("import request from './request'",'const request=globalThis.__runQa')
  source=source.replace("import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from './eventBus'",'const eventBus={on(){},off(){}}, EVENT_AUTH_CHANGED="changed", EVENT_AUTH_EXPIRED="expired"')
  source=source.replace("from './runOverview'",`from '${new URL('../src/utils/runOverview.ts',import.meta.url).href}'`)
  const output=fileURLToPath(new URL(`.run-monitor-${process.pid}.mjs`,import.meta.url))
  await writeFile(output,ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText)
  let monitor
  try {
    monitor=await import(pathToFileURL(output).href)
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunItems.value[0].status,'succeeded','completion while closed is restored')
    assert.equal(monitor.aiRunCount.value,1)
    monitor.markAiRunRead('101')
    assert.equal(monitor.aiRunCount.value,0)
    response=new Error('offline');await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunConnection.value,'reconnecting')
    response={code:200,data:{items:[run('running','102')],serverTime:'2026-10-05T11:02:00Z'}}
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunConnection.value,'online')
    assert.equal(monitor.aiRunCount.value,1)
    let resolveOld
    deferred=new Promise(resolve=>{resolveOld=resolve})
    const before=calls
    const pending=monitor.refreshAiRuns(), duplicate=monitor.refreshAiRuns()
    assert.equal(calls,before+1,'polls are single-flight')
    localStorage.setItem('userId','8');localStorage.setItem('token','other')
    deferred=null;response={code:200,data:{items:[run('awaiting_approval','201')],serverTime:'2026-10-05T11:03:00Z'}}
    await monitor.refreshAiRuns()
    resolveOld({code:200,data:{items:[run('succeeded','102')],serverTime:'2026-10-05T11:03:00Z'}})
    await Promise.all([pending,duplicate])
    assert.deepEqual(monitor.aiRunItems.value.map(r=>r.conversationId),['201'],'old-account result cannot overwrite new account')
    localStorage.removeItem('token');await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunCount.value,0)
  } finally {monitor?.stopAiRunMonitor();await unlink(output);dom.window.close();delete globalThis.__runQa}
})
