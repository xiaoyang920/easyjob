import test from 'node:test'
import assert from 'node:assert/strict'
import { conversationScope, conversationCategory, writingSourceTitle } from '../src/utils/conversationScope.ts'
import { knownWritingConversations, writingBindingKey } from '../src/utils/writingConversations.ts'

test('writing is a distinct source and never routed as public article Q&A', () => {
  assert.equal(conversationScope({}), 'general')
  assert.equal(conversationScope({ originArticleId: '42' }), 'article')
  for (const isWriting of [true, 1, '1']) assert.equal(conversationScope({ isWriting, writingArticleId: '42' }), 'writing')
  assert.equal(conversationCategory({ isWriting: true }), '草稿写作')
  assert.equal(writingSourceTitle({ isWriting: true }), '未保存草稿')
  assert.equal(writingSourceTitle({ writingArticleId: '42' }), '草稿暂不可用')
})
test('legacy migration uses only exact associations for the current account and skips confirmed bindings', () => {
  const values = new Map([
    ['easyjob:writing-conversation:7:42', '101'], ['easyjob:writing-conversation:7:new', '102'],
    ['easyjob:writing-conversation:8:42', '201'], ['easyjob:writing-conversation:7:other', '301']
  ])
  const storage = { get length() { return values.size }, key: index => [...values.keys()][index] || null, getItem: key => values.get(key) ?? null }
  assert.deepEqual(knownWritingConversations(storage, '7'), [{ scope: '42', id: '101' }, { scope: 'new', id: '102' }])
  values.set(writingBindingKey('7', '42'), '101')
  assert.deepEqual(knownWritingConversations(storage, '7'), [{ scope: 'new', id: '102' }])
  assert.deepEqual(knownWritingConversations(storage, null), [])
})
