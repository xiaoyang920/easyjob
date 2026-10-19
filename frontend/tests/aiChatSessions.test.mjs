// Mount the real SFC and feed controlled SSE responses. No external APIs or real user data.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, writeFile, unlink } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import { JSDOM } from 'jsdom'

test('real chat component switches, receives parallel replies, resumes and cancels only its own run', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url:'http://localhost:3000/ai-chat', pretendToBeVisual:true })
  for (const key of ['window','document','Element','HTMLElement','SVGElement','Node','localStorage','DOMParser']) globalThis[key] = dom.window[key]
  globalThis.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window)
  globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window)
  globalThis.CSS = dom.window.CSS || {escape:value=>String(value).replace(/[^a-zA-Z0-9_-]/g, character=>'\\'+character)}
  globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window)
  localStorage.setItem('token', 'isolated-unit-test')
  localStorage.setItem('userId', 'qa')
  const vue = await import('vue')
  const source = fileURLToPath(new URL('../src/views/AiChat.vue', import.meta.url))
  const { descriptor } = parse(await readFile(source, 'utf8'))
  let script = compileScript(descriptor, { id:'chat-session-qa', inlineTemplate:true }).content
  const editorPath = fileURLToPath(new URL(`.draft-editor-qa-${process.pid}.mjs`,import.meta.url))
  const editorSource = parse(await readFile(new URL('../src/components/AiDraftEditor.vue',import.meta.url),'utf8')).descriptor
  let editorScript = compileScript(editorSource,{id:'draft-editor-qa',inlineTemplate:true}).content
  editorScript = editorScript.replace(/^import .* from ['"]element-plus['"]\s*$/gm, `
    const {h:hQa}=await import('vue')
    const ElMessage={warning:()=>{}}
    const ElDialog={props:['modelValue'],setup:(props,{slots})=>()=>props.modelValue?hQa('section',{},[slots.default?.(),slots.footer?.()]):null}
  `).replace(/^import .* from ['"][^'"]+\.vue['"]\s*$/gm, `
    const ArticleRichEditor={props:['modelValue'],emits:['update:modelValue'],setup:(props,{emit})=>()=>hQa('textarea',{class:'rich-editor-stub',value:props.modelValue,onInput:e=>emit('update:modelValue',e.target.value)})}
  `).replace(/from ['"](@\/[^'"]+)['"]/g,(_,name)=>`from '${pathToFileURL(path.resolve(path.dirname(source),'../',name.slice(2))+'.ts').href}'`)
  await writeFile(editorPath,ts.transpileModule(editorScript,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText)
  const streams = [], calls = [], notices = [], histories = new Map()
  let recovering = false
  const encoder = new TextEncoder()
  const fetchStream = async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : null
    const item = { url, body, signal:options.signal, emit(data) { this.controller.enqueue(encoder.encode(`data:${data}\n\n`)) }, finish() { this.emit('[DONE]'); this.controller.close() } }
    const response = new Response(new ReadableStream({ start(controller) {
      item.controller = controller
      options.signal.addEventListener('abort', () => { try { controller.error(new DOMException('stopped','AbortError')) } catch {} }, {once:true})
    } }))
    streams.push(item)
    return response
  }
  const chats = [{conversationId:'101',title:'会话 A'},{conversationId:'102',title:'会话 B'}]
  let stoppedB = false
  globalThis.__chatQa = {
    route:vue.reactive({query:{}}), router:{push:async()=>{},replace:async()=>{}}, fetch:fetchStream,
    message:Object.assign(message=>notices.push(message),Object.fromEntries(['info','success','error','warning'].map(k=>[k,message=>notices.push(message)]))),
    request:{
      async get(url, options) {
        calls.push(['get',url])
        if(url==='/agent/library') return {code:200,data:{rows:options.params.scope==='general'?chats:[],total:options.params.scope==='general'?chats.length:0}}
        if(url==='/agent/conversations') return {code:200,data:options.params.scope==='general'?chats:[]}
        if(url.endsWith('/messages')) return {code:200,data:histories.get(url.split('/')[3]) || []}
        if(url.endsWith('/run')) return {code:200,data:stoppedB&&url.includes('102')?{runId:'run-b',status:'cancelled'}:recovering&&url.includes('101')?{runId:'r-recovered',status:'running'}:null}
        throw new Error(url)
      },
      async post(url) {
        calls.push(['post',url])
        if (url==='/agent/chat/102/cancel') {
          assert.equal(streams[1].signal.aborted,true,'release the SSE connection before the cancel request so a saturated HTTP connection pool cannot queue the stop')
          stoppedB = true
          throw new Error('simulated lost response after server committed cancellation')
        }
        if (url==='/agent/chat/101/cancel') throw new Error('simulated stop request not delivered')
        return {code:200,data:{status:'cancelled'}}
      },
      async delete(url) { calls.push(['delete',url]); return {code:200} }
    }
  }
  script = script.replace(/^import .* from ['"]([^'"]+\.vue)['"]\s*$/gm, line => {
    const name=line.match(/^import (\w+)/)[1]
    if(name==='AiConversationItem') return `const {h:conversationRow}=await import('vue');const AiConversationItem={props:['conversation','status'],emits:['select'],setup:(props,{emit})=>()=>conversationRow('button',{class:'conversation-item',onClick:()=>emit('select')},props.conversation.title+' '+(props.status || ''))}`
    if(name==='CodeContent') return `const {h:codeRoot}=await import('vue');const CodeContent={props:['html'],setup:props=>()=>codeRoot('div',{innerHTML:props.html})}`
    return name==='AiDraftEditor'?`const AiDraftEditor=(await import('${pathToFileURL(editorPath).href}')).default`:`const ${name} = {render:()=>null}`
  })
  script = script.replace(/^import .* from ['"]vue-router['"]\s*$/gm, 'const useRouter=()=>globalThis.__chatQa.router, useRoute=()=>globalThis.__chatQa.route')
  script = script.replace(/^import .* from ['"]element-plus['"]\s*$/gm, 'const ElMessage=globalThis.__chatQa.message')
  script = script.replace(/^import .* from ['"]@\/utils\/request['"]\s*$/gm, 'const request=globalThis.__chatQa.request')
  script = script.replace(/^import .* from ['"]@\/utils\/authSession['"]\s*$/gm, 'const authenticatedFetch=globalThis.__chatQa.fetch')
  script = script.replace(/^import .* from ['"]@\/utils\/aiRuns['"]\s*$/gm, 'const aiConversationStatus=()=>"", setViewedAiConversation=()=>{}, trackAiRun=()=>{}, refreshAiRuns=async()=>{}')
  script = script.replace(/from ['"](@\/[^'"]+|\.\.\/[^'"]+)['"]/g, (_,name) => {
    const file = name.startsWith('@/') ? path.resolve(path.dirname(source),'../',name.slice(2)) : path.resolve(path.dirname(source),name)
    return `from '${pathToFileURL(file+'.ts').href}'`
  })
  const compiled = ts.transpileModule(script, { compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext} }).outputText
  const modulePath = fileURLToPath(new URL(`.chat-session-qa-${process.pid}.mjs`,import.meta.url))
  await writeFile(modulePath, compiled)
  let app
  const tick = async () => { await new Promise(resolve=>setTimeout(resolve,5)); await vue.nextTick() }
  const settle = async (predicate) => {
    for(let i=0;i<100;i++) { if(predicate()) return; await tick() }
    assert.ok(predicate(),'expected UI update')
  }
  const click = async el => { assert.ok(el,'button exists'); el.click(); await tick() }
  const button = text => [...document.querySelectorAll('button')].find(el=>el.textContent.trim()===text)
  const select = title => click([...document.querySelectorAll('.conversation-item')].find(el=>el.textContent.includes(title)))
  const input = () => document.querySelector('textarea[placeholder]')
  const send = async text => { input().value=text; input().dispatchEvent(new window.Event('input',{bubbles:true})); await tick(); await click(document.querySelector('[aria-label="发送消息"]')) }
  const reply = (stream,text) => {
    if(stream.body) histories.set(stream.body.conversationId || '103',[{role:'user',content:stream.body.message},{role:'assistant',content:text}])
    stream.emit('__REPLY__:'+JSON.stringify({content:text})); stream.emit('__PROGRESS__:done'); stream.finish()
  }
  try {
    const component = (await import(pathToFileURL(modulePath).href)).default
    app=vue.createApp(component)
    app.config.warnHandler=()=>{}
    app.component('RouterLink',{template:'<a><slot/></a>'})
    app.component('el-dialog',{template:'<div v-if="false"/>'})
    app.mount('#root')
    await settle(()=>document.querySelectorAll('.conversation-item').length===2)
    await select('会话 A')
    await send('A 的问题')
    await settle(()=>streams.length===1)
    streams[0].emit('__RUN_ID__:run-a')
    streams[0].emit('__PREVIEW__:{"type":"replace","content":"A 的部分回答"}')
    await tick()
    assert.ok(!document.querySelector('.message-list').textContent.includes('A 的部分回答'),'unverified preview stays private')
    streams[0].emit('__PREVIEW__:{"type":"delta","content":"继续生成"}')
    await tick()
    assert.ok(!document.querySelector('.message-list').textContent.includes('A 的部分回答继续生成'))
    streams[0].emit('__ANSWER__:{"type":"start","mode":"direct"}')
    streams[0].emit('__ANSWER__:{"type":"delta","seq":0,"content":"A 的实时回答"}')
    await settle(()=>document.querySelector('.message-list').textContent.includes('A 的实时回答'))
    assert.ok(document.querySelector('[aria-label="停止生成"]'),'live text is visible before the run completes')
    streams[0].emit('__ANSWER__:{"type":"delta","seq":0,"content":"A 的实时回答"}')
    await tick()
    assert.equal(document.querySelector('.message-list').textContent.split('A 的实时回答').length - 1,1,'replay does not duplicate live chunks')
    await select('会话 B')
    assert.equal(input().disabled,false,'other chat remains usable')
    streams[0].emit('__ANSWER__:{"type":"delta","seq":1,"content":"，后台继续"}')
    await tick()
    assert.ok(!document.querySelector('.message-list')?.textContent.includes('后台继续'),'background live text cannot leak into B')
    await send('B 的问题')
    await settle(()=>streams.length===2)
    streams[1].emit('__RUN_ID__:run-b')
    assert.equal(streams[0].signal.aborted,false,'switch does not cancel A')
    reply(streams[0],'A 的完整回答')
    await tick()
    assert.ok(!document.querySelector('.message-list').textContent.includes('A 的完整回答'),'background result cannot leak into B')
    assert.ok(document.querySelector('.conversation-list').textContent.includes('有新回复'))
    assert.ok(document.querySelector('[aria-label="停止生成"]'),'A completion must not unlock B')
    await select('会话 A')
    assert.ok(document.querySelector('.message-list').textContent.includes('A 的完整回答'))
    await select('会话 B')
    assert.equal(streams.length,2,'switching back does not add a duplicate stream')
    await click(document.querySelector('[aria-label="停止生成"]'))
    assert.ok(calls.some(([method,url])=>method==='post'&&url==='/agent/chat/102/cancel'))
    assert.equal(streams[0].signal.aborted,false)
    assert.equal(streams[1].signal.aborted,true)
    await settle(()=>!input().disabled)
    assert.ok(document.querySelector('.message-list').textContent.includes('已停止处理'),'a lost cancel response is reconciled with authoritative run status')
    assert.ok(!notices.some(message=>message.includes('停止失败')))
    await click(button('开启新对话'))
    await send('没有 ID 时发起的问题')
    await settle(()=>streams.length===3)
    await click(button('开启新对话'))
    input().value='新对话未发送的输入'; input().dispatchEvent(new window.Event('input',{bubbles:true}))
    streams[2].emit('__CONV_ID__:103')
    reply(streams[2],'晚到的新会话回答')
    await tick()
    assert.equal(input().value,'新对话未发送的输入')
    assert.equal(document.querySelector('.message-list'),null,'late ID does not navigate the selected blank chat')
    // A draft approval has its own reader too, even when the user leaves during saving.
    await select('会话 A')
    await send('生成待确认草稿')
    await settle(()=>streams.length===4)
    const draftPayload={runId:'draft-run',draftHash:'qa-hash',title:'隔离草稿',draft:'草稿正文。\n\n来源：[research:web1]',citations:[{id:'research:web1',title:'学校简介',url:'https://example.org/intro'}]}
    streams[3].emit('__INTERRUPTED__:'+JSON.stringify(draftPayload))
    await tick()
    assert.equal(document.querySelector('.draft-review-body').textContent.trim(),'草稿正文。','draft preview shows prose, while its source mapping stays in the approval payload')
    assert.equal(document.querySelector('.draft-review-card .inline-citation'),null)
    assert.equal(document.querySelector('.citation-list'),null,'drafts do not display the chat source list')
    streams[3].finish()
    histories.set('101',[{role:'user',content:'生成待确认草稿'},{role:'assistant',content:'草稿正文',interrupted:true,isDraft:true,interruptPayload:draftPayload}])
    await settle(()=>button('保存草稿'))
    await click(button('直接编辑'))
    const title=document.querySelector('.editor-fields input')
    title.value='我修改的标题';title.dispatchEvent(new window.Event('input',{bubbles:true}));await tick()
    assert.equal(document.querySelector('.rich-editor-stub').value.trim(),'<p>草稿正文。</p>','the rich editor starts without generated citations')
    await click(button('应用修改'))
    assert.equal(document.querySelector('.draft-review-body').textContent.trim(),'草稿正文。')
    await click(button('直接编辑'))
    const body=document.querySelector('.rich-editor-stub')
    body.value='<h1>手动正文</h1><p>代码与图片链接</p>';body.dispatchEvent(new window.Event('input',{bubbles:true}));await tick()
    await click(button('应用修改'))
    assert.ok(document.querySelector('.draft-review-body h1').textContent.includes('手动正文'))
    await click(button('保存草稿'))
    await settle(()=>streams.length===5)
    assert.equal(streams[4].body.conversationId,'101')
    assert.equal(streams[4].body.runId,'draft-run')
    assert.equal(streams[4].body.editedDraft.title,'我修改的标题')
    assert.equal(streams[4].body.editedDraft.content,'<h1>手动正文</h1><p>代码与图片链接</p>')
    assert.equal(streams[4].body.editedDraft.content_format,'html')
    await select('会话 B')
    streams[4].emit('__DRAFT_SAVED__:{"draftArticleId":"900","title":"隔离草稿"}')
    reply(streams[4],'草稿已保存')
    histories.set('101',[{role:'assistant',content:'草稿已保存',draftArticleId:'900',draftTitle:'隔离草稿'}])
    await tick()
    assert.ok(!document.body.textContent.includes('草稿已保存'),'approval reply must not overwrite B')
    await select('会话 A')
    assert.ok(document.querySelector('.draft-link').textContent.includes('隔离草稿'))
    await select('会话 B')
    // A page reload recovery still displays partial output while loading the run.
    recovering=true
    await select('会话 A')
    await settle(()=>streams.length===6)
    streams[5].emit('__REPLY__:{"content":"恢复中的回答"}')
    await tick()
    assert.ok(document.querySelector('.message-list').textContent.includes('恢复中的回答'))
    assert.ok(!document.body.textContent.includes('加载中...'),'history loading does not hide a live replay')
    const messageCount = document.querySelector('.message-list').getAttribute('data-message-count')
    await click(document.querySelector('[aria-label="停止生成"]'))
    await settle(()=>streams.length===7)
    assert.equal(streams[5].signal.aborted,true)
    assert.equal(document.querySelector('.message-list').getAttribute('data-message-count'),messageCount,'reconnecting after an undelivered stop reuses the same run message')
    await select('会话 B')
    assert.equal(streams[6].signal.aborted,false)
    assert.equal(input().disabled,false)
    app.unmount(); app=null
    assert.equal(streams[6].signal.aborted,true,'unmount releases all readers')
  } finally {
    app?.unmount()
    await unlink(modulePath)
    await unlink(editorPath)
    dom.window.close()
    delete globalThis.__chatQa
  }
})
