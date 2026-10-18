import test from 'node:test'
import assert from 'node:assert/strict'
import { SseDecoder, readSse, createAgentState, applyAgentEvent, applyAnswerChunk, setRunStatus, restoreAgentState } from '../src/utils/agentStream.ts'

test('failed history restores completed work and failure without restarting the duration clock', () => {
  const message = { runStatus: 'failed', runStartedAt: '2026-10-11T01:00:00Z', runFinishedAt: '2026-10-11T01:00:20Z', agentEvents: [
    { version: 1, kind: 'activity', id: 'a', label: '检索', status: 'active', timestamp: '2026-10-11T01:00:02Z' },
    { version: 1, kind: 'activity', id: 'a', label: '检索', status: 'done', timestamp: '2026-10-11T01:00:05Z' },
    { version: 1, kind: 'activity', id: 'b', label: '分析', status: 'active', timestamp: '2026-10-11T01:00:06Z' },
  ] }
  const restored = restoreAgentState(message)
  assert.equal(restored.status, 'error')
  assert.deepEqual(restored.activities.map(item => item.status), ['done', 'error'])
  assert.equal(restored.finishedAt - restored.startedAt, 20000)
  assert.equal(restored.activities[0].finishedAt - restored.activities[0].startedAt, 3000)
  assert.deepEqual(restoreAgentState(message), restored)
  assert.equal(restoreAgentState({ content: '普通历史' }), undefined)
})

test('approval conflict shows the server message rather than a generic HTTP error', async () => {
  const response = new Response(JSON.stringify({ code: 409, message: '草稿版本已更新，请重新加载' }),
    { status: 409, headers: { 'Content-Type': 'application/json' } })
  await assert.rejects(async () => { for await (const frame of readSse(response)) {} }, /草稿版本已更新，请重新加载/)
})

test('chat conflicts retain HTTP status so the UI can discover and reconnect the active run', async () => {
  const response = new Response(JSON.stringify({ code: 409, message: '会话已有运行' }), { status: 409 })
  await assert.rejects(async () => { for await (const frame of readSse(response)) {} }, error => error.status === 409)
})

test('an empty conflict response still explains how to recover', async () => {
  const response = new Response('', { status: 409 })
  await assert.rejects(async () => { for await (const frame of readSse(response)) {} }, /重新加载会话/)
})

test('SSE handles split CRLF, multiline data, comments and an ending frame', () => {
  const decoder = new SseDecoder()
  assert.deepEqual(decoder.push(': heartbeat\r\ndata: first\r'), [])
  assert.deepEqual(decoder.push('\ndata: second\r\n\r'), [])
  assert.deepEqual(decoder.push('\ndata:last'), ['first\nsecond'])
  assert.deepEqual(decoder.finish(), ['last'])
})

test('UTF-8 network fragments preserve Chinese, emoji and code escapes', async () => {
  const text = '中文🙂\nconst path = "C:\\new\\file"'
  const data = '__ANSWER__:' + JSON.stringify({ type: 'delta', seq: 0, content: text })
  const bytes = new TextEncoder().encode(`data:${data}\n\ndata:[DONE]\n\n`)
  const response = new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
    controller.close()
  } }))
  const frames = []
  for await (const frame of readSse(response)) frames.push(frame)
  assert.equal(JSON.parse(frames[0].slice('__ANSWER__:'.length)).content, text)
  assert.equal(frames[1], '[DONE]')
})

test('parallel task updates are distinct, deduplicated and retained on completion', () => {
  const state = createAgentState()
  applyAgentEvent(state, { version: 1, kind: 'plan', tasks: [
    { id: 'a', label: '研究A', role: 'search', stage: 1 }, { id: 'b', label: '研究B', role: 'search', stage: 1 }
  ] })
  for (const id of ['a', 'b']) applyAgentEvent(state, { version: 1, kind: 'activity', id: `${id}/task`, taskId: id,
    step: 'task', label: '检索资料', actor: 'subagent', status: 'active' })
  assert.deepEqual(state.plan.map(task => task.status), ['active', 'active'])
  applyAgentEvent(state, { version: 1, kind: 'activity', id: 'a/task', taskId: 'a', step: 'task', label: '检索资料', status: 'done' })
  assert.equal(state.activities.length, 2)
  assert.deepEqual(state.plan.map(task => task.status), ['done', 'active'])
  setRunStatus(state, 'complete')
  assert.equal(state.activities.length, 2)
  assert.deepEqual(state.plan.map(task => task.status), ['done', 'done'])
})

test('complete plan text survives live events and history restoration beyond the old 120 character cut', () => {
  const label = '核实角色出处，'.repeat(38) + '最后核对纳兰嫣然的服饰与原始发布来源。'
  const event = { version: 1, kind: 'plan', tasks: [{ id: 'source', label, role: 'search', stage: 1 }] }
  const state = createAgentState()
  applyAgentEvent(state, event)
  assert.equal(state.plan[0].label, label)
  const restored = restoreAgentState({ runStatus: 'succeeded', agentEvents: [event] })
  assert.equal(restored.plan[0].label, label)
  assert.ok(restored.plan[0].label.endsWith('原始发布来源。'))
})

test('plan length guard respects Unicode characters without splitting an emoji', () => {
  const state = createAgentState()
  const label = '图'.repeat(3999) + '🙂' + '尾部超出服务端任务上限'
  applyAgentEvent(state, { version: 1, kind: 'plan', tasks: [{ id: 'long', label, role: 'search', stage: 1 }] })
  assert.equal(state.plan[0].label, '图'.repeat(3999) + '🙂')
  assert.equal(Array.from(state.plan[0].label).length, 4000)
})

test('draft approval is paused until save and errors are not shown as successes', () => {
  const state = createAgentState()
  applyAgentEvent(state, { version: 1, kind: 'plan', tasks: [{ id: 'draft', label: '写草稿', role: 'writing', stage: 1 }] })
  applyAgentEvent(state, { version: 1, kind: 'activity', id: 'draft/approve', taskId: 'draft', step: 'approve_draft', label: '确认', status: 'paused' })
  setRunStatus(state, 'awaiting')
  assert.equal(state.plan[0].status, 'paused')
  setRunStatus(state, 'working')
  applyAgentEvent(state, { version: 1, kind: 'activity', id: 'draft/save', taskId: 'draft', step: 'save_draft', label: '保存', status: 'done' })
  assert.equal(state.plan[0].status, 'done')
  setRunStatus(state, 'error')
  assert.equal(state.status, 'error')
})

test('answer chunks reject gaps, ignore duplicate delivery and preserve exact content', () => {
  const state = createAgentState()
  let text = applyAnswerChunk(state, 'old', { type: 'start' })
  assert.equal(text, '')
  text = applyAnswerChunk(state, text, { type: 'delta', seq: 0, content: '中文\\n' })
  text = applyAnswerChunk(state, text, { type: 'delta', seq: 0, content: '中文\\n' })
  assert.equal(text, '中文\\n')
  assert.throws(() => applyAnswerChunk(state, text, { type: 'delta', seq: 2, content: 'bad' }))
  applyAnswerChunk(state, text, { type: 'end', chunks: 1 })
  assert.equal(state.answerReceiving, false)
})

test('incremental plans retain earlier task outcomes and unsupported events do not reset progress', () => {
  const state = createAgentState()
  applyAgentEvent(state, { version: 1, kind: 'plan', tasks: [{ id: 'a', label: 'A', role: 'search', stage: 1 }] })
  applyAgentEvent(state, { version: 1, kind: 'activity', id: 'a/task', taskId: 'a', step: 'task', label: 'A', status: 'error' })
  applyAgentEvent(state, { version: 1, kind: 'plan', tasks: [{ id: 'b', label: 'B', role: 'search', stage: 1 }] })
  assert.deepEqual(state.plan.map(task => task.id), ['a', 'b'])
  assert.equal(state.plan[0].status, 'error')
  applyAgentEvent(state, { version: 2, kind: 'activity', id: 'unknown', label: 'bad', status: 'done' })
  assert.equal(state.activities.length, 1)
})

test('memory retrieval remains a main task alongside later knowledge retrieval', () => {
  const state = createAgentState()
  applyAgentEvent(state, { version: 1, kind: 'plan', mode: 'retrieve', tasks: [
    { id: 'history', label: '查找历史决策', role: 'memory', stage: 1 }] })
  applyAgentEvent(state, { version: 1, kind: 'activity', id: 'history/task', taskId: 'history',
    step: 'task', actor: 'main', label: '召回相关记忆', status: 'active' })
  applyAgentEvent(state, { version: 1, kind: 'activity', id: 'history/task', taskId: 'history',
    step: 'task', actor: 'main', label: '召回相关记忆', status: 'done' })
  applyAgentEvent(state, { version: 1, kind: 'plan', mode: 'retrieve', tasks: [
    { id: 'source', label: '查找文章', role: 'search', stage: 1 }] })
  assert.deepEqual(state.plan.map(task => [task.role, task.status]), [['memory', 'done'], ['search', 'pending']])
  assert.equal(state.activities[0].actor, 'main')
  assert.equal(state.activities[0].label, '召回相关记忆')
})
