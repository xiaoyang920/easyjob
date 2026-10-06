import test from 'node:test'
import assert from 'node:assert/strict'
import { createChatSession, bindConversationId, beginChatOperation, finishChatOperation, releaseChatSessions } from '../src/utils/chatSessions.ts'

test('late conversation IDs stay attached to the originating session', () => {
  const a = createChatSession('local-a'), b = createChatSession('local-b')
  const sessions = new Map([['local-a', a], ['local-b', b]])
  b.userInput = '另一会话的未发送问题'
  bindConversationId(sessions, a, '101')
  assert.equal(sessions.get('101'), a)
  assert.equal(b.conversationId, null)
  assert.equal(b.userInput, '另一会话的未发送问题')
  assert.throws(() => bindConversationId(sessions, b, '101'))
  assert.equal(sessions.get('101'), a)
})

test('old completion cannot unlock a newer generation or clear its connection', () => {
  const a = createChatSession('a', '101'), b = createChatSession('b', '102')
  const old = beginChatOperation(a)
  beginChatOperation(b)
  const current = beginChatOperation(a)
  const controller = a.abortController = new AbortController()
  assert.equal(finishChatOperation(a, old), false)
  assert.equal(a.loading, true)
  assert.equal(a.abortController, controller)
  assert.equal(finishChatOperation(a, current), true)
  assert.equal(a.loading, false)
  assert.equal(b.loading, true)
})

test('leaving the page releases every reader including pending conversations', () => {
  const a = createChatSession('a'), b = createChatSession('b', '102')
  const ca = a.abortController = new AbortController(), cb = b.abortController = new AbortController()
  releaseChatSessions([a, a, b])
  assert.equal(ca.signal.aborted, true)
  assert.equal(cb.signal.aborted, true)
  assert.equal(a.abortController, null)
  assert.equal(b.abortController, null)
})
