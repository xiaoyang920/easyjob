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
  const realNow=Date.now
  try {
    monitor=await import(pathToFileURL(output).href)
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunItems.value[0].status,'succeeded','completion while closed is restored')
    assert.equal(monitor.aiRunCount.value,1)
    monitor.markAiRunRead('101')
    assert.equal(monitor.aiRunCount.value,0)
    monitor.startAiRunMonitor()
    await new Promise(r=>setImmediate(r))
    const beforeStorage=calls
    const shared=JSON.stringify({items:[{...run('succeeded'),unread:false}],syncedAt:'2026-10-05T11:01:00Z'})
    for(let i=0;i<50;i++)window.dispatchEvent(new window.StorageEvent('storage',{key:'ai_run_notices:7',newValue:shared}))
    await new Promise(r=>setImmediate(r))
    assert.equal(calls,beforeStorage,'another tab cache never triggers HTTP or a storage feedback loop')
    response=new Error('offline');await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunConnection.value,'reconnecting')
    const beforeRetry=calls;await monitor.refreshAiRuns();assert.equal(calls,beforeRetry,'errors back off before retrying')
    Date.now=()=>realNow()+16000
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
  } finally {Date.now=realNow;monitor?.stopAiRunMonitor();await unlink(output);dom.window.close();delete globalThis.__runQa}
})

test('visible live replies stay read through delayed polls, reloads and stale cross-tab snapshots', async () => {
  const dom = new JSDOM('', { url: 'http://localhost', pretendToBeVisual: true })
  globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.localStorage = dom.window.localStorage
  localStorage.setItem('userId', '7'); localStorage.setItem('token', 'qa')
  let now = 10000, visibility = 'visible', calls = 0, deferred = null
  Object.defineProperty(document, 'visibilityState', { get: () => visibility })
  const run = (status = 'running', time = '2026-10-21T10:00:00Z') => ({ runId: 'r', conversationId: '101', title: '问题', scope: 'writing', status, updatedAt: time })
  let response = { code: 200, data: { items: [run()], serverTime: '2026-10-21T10:00:01Z' } }
  globalThis.__readRunQa = { get: async () => { calls++; return deferred || response } }
  let source = await readFile(new URL('../src/utils/aiRuns.ts', import.meta.url), 'utf8')
  source = source.replace("import request from './request'", 'const request=globalThis.__readRunQa')
    .replace("import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from './eventBus'", 'const eventBus={on(){},off(){}}, EVENT_AUTH_CHANGED="changed", EVENT_AUTH_EXPIRED="expired"')
    .replace("from './runOverview'", `from '${new URL('../src/utils/runOverview.ts', import.meta.url).href}'`)
  const output = fileURLToPath(new URL(`.read-run-monitor-${process.pid}.mjs`, import.meta.url))
  await writeFile(output, ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText)
  const realNow = Date.now
  let monitor, reloaded
  try {
    Date.now = () => now
    monitor = await import(pathToFileURL(output).href)
    await monitor.refreshAiRuns()
    let resolveOld
    deferred = new Promise(resolve => { resolveOld = resolve })
    const pending = monitor.refreshAiRuns()
    now++
    monitor.setViewedAiConversation('101', 'r')
    monitor.markAiRunRead('101', 'r') // The live answer was read before the poll knew it had finished.
    monitor.setViewedAiConversation(null)
    resolveOld(response); await pending; deferred = null
    now++
    response = { code: 200, data: { items: [run('succeeded')], serverTime: '2026-10-21T10:00:02Z' } }
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunCount.value, 0, 'switching chats before the terminal poll must not resurrect a read reply')
    const receipt = JSON.parse(localStorage.getItem('ai_run_reads:7'))[0][1]
    assert.equal(receipt.updatedAt, run().updatedAt, 'a fresh poll pins the pending receipt to an exact server version')

    // An older tab may still persist unread=true. The independent read receipt wins after reload.
    const shared = JSON.stringify({ items: [{ ...run('succeeded'), unread: true }], syncedAt: response.data.serverTime })
    localStorage.setItem('ai_run_notices:7', shared)
    reloaded = await import(pathToFileURL(output).href + '?reload=1')
    await reloaded.refreshAiRuns()
    assert.equal(reloaded.aiRunCount.value, 0, 'durable read receipt survives a stale snapshot and module reload')

    monitor.startAiRunMonitor(); await new Promise(resolve => setImmediate(resolve))
    const beforeStorage = calls
    window.dispatchEvent(new window.StorageEvent('storage', { key: 'ai_run_notices:7', newValue: shared }))
    assert.equal(monitor.aiRunCount.value, 0)
    assert.equal(calls, beforeStorage, 'storage events must never trigger recursive polling')

    now++
    response = { code: 200, data: { items: [run('succeeded', '2026-10-21T10:01:00Z')], serverTime: '2026-10-21T10:01:01Z' } }
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunItems.value[0].unread, true, 'a later completion of a recovered run is a new version')
    const readInOtherTab = JSON.stringify([['101', { runId: 'r', status: 'succeeded', updatedAt: response.data.items[0].updatedAt, seenAt: ++now }]])
    window.dispatchEvent(new window.StorageEvent('storage', { key: 'ai_run_reads:7', newValue: readInOtherTab }))
    assert.equal(monitor.aiRunCount.value, 0, 'another tab reading this exact version clears the notice')

    visibility = 'hidden'
    monitor.setViewedAiConversation('101', 'r')
    now++
    response = { code: 200, data: { items: [run('succeeded', '2026-10-21T10:02:00Z')], serverTime: '2026-10-21T10:02:01Z' } }
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunItems.value[0].unread, true, 'a hidden tab cannot acknowledge a newer reply')

    visibility = 'visible'
    monitor.setViewedAiConversation('101', 'r', 0)
    now++
    response = { code: 200, data: { items: [{ ...run('succeeded', '2026-10-21T10:03:00Z'), generation: 1 }], serverTime: '2026-10-21T10:03:01Z' } }
    await monitor.refreshAiRuns()
    assert.equal(monitor.aiRunItems.value[0].unread, true, 'an old visible answer cannot acknowledge a later execution of the same run')
    monitor.markAiRunRead('101', 'r', 0)
    assert.equal(monitor.aiRunItems.value[0].unread, true, 'a delayed old read callback cannot clear the recovered reply')
    monitor.setViewedAiConversation('101', 'r', 1)
    assert.equal(monitor.aiRunCount.value, 0, 'viewing the actual recovered reply acknowledges its own generation')
  } finally {
    Date.now = realNow; monitor?.stopAiRunMonitor(); reloaded?.stopAiRunMonitor()
    await unlink(output); dom.window.close(); delete globalThis.__readRunQa
  }
})
