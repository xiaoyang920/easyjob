import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile,writeFile,unlink} from 'node:fs/promises'
import {fileURLToPath,pathToFileURL} from 'node:url'
import ts from 'typescript'

test('notification reconnect has one owner, backs off and fences stale connections and accounts',async()=>{
 const store=new Map([['userId','7'],['token','qa']]),timers=new Map(),sources=[];let next=0,calls=0,pending=null,tokenPending=null
 globalThis.localStorage={getItem:key=>store.get(key)??null}
 globalThis.window={setTimeout:(fn,delay)=>{timers.set(++next,{fn,delay});return next},clearTimeout:id=>timers.delete(id)}
 globalThis.EventSource=class{constructor(){this.handlers=new Map();this.closed=false;sources.push(this)}addEventListener(name,fn){this.handlers.set(name,fn)}close(){this.closed=true}}
 globalThis.__notifyQa={request:{get:async()=>{calls++;return pending??{data:0}}},token:()=>tokenPending??Promise.resolve('qa')}
 const input=fileURLToPath(new URL('../src/utils/notification.ts',import.meta.url)),output=fileURLToPath(new URL(`.notify-qa-${process.pid}.mjs`,import.meta.url))
 let source=await readFile(input,'utf8');source=source.replace("import request from './request'",'const request=globalThis.__notifyQa.request').replace("import { ensureAccessToken } from './authSession'",'const ensureAccessToken=()=>globalThis.__notifyQa.token()')
 await writeFile(output,ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText)
 let service
 try{
  service=await import(pathToFileURL(output).href)
  await Promise.all([service.connectNotifyStream(),service.connectNotifyStream()]);assert.equal(sources.length,1)
  sources[0].onerror();assert.equal(sources[0].closed,true);assert.equal([...timers.values()][0].delay,5000)
  await service.connectNotifyStream();assert.equal(sources.length,1,'page mounts cannot bypass reconnect backoff')
  const timer=[...timers.values()][0];timers.clear();timer.fn();await new Promise(r=>setImmediate(r));assert.equal(sources.length,2)
  sources[0].onerror();assert.equal(sources[1].closed,false,'old source cannot close its replacement')
  sources[1].onerror();assert.equal([...timers.values()][0].delay,10000)
  service.closeNotifyStream();assert.equal(timers.size,0)
  let resolveToken;tokenPending=new Promise(r=>resolveToken=r);const connecting=service.connectNotifyStream();service.closeNotifyStream();resolveToken('qa');await connecting;assert.equal(sources.length,2,'logout fences an in-flight handshake')
  let resolveCount;pending=new Promise(r=>resolveCount=r);const a=service.fetchNotifyUnreadCount(),b=service.fetchNotifyUnreadCount();assert.equal(calls,1)
  store.set('userId','8');resolveCount({data:5});await Promise.all([a,b]);assert.equal(service.notifyUnreadCount.value,0,'old account result is ignored')
 }finally{service?.closeNotifyStream();await unlink(output);delete globalThis.__notifyQa;delete globalThis.EventSource;delete globalThis.window;delete globalThis.localStorage}
})
