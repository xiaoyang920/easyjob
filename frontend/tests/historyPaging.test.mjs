import test from 'node:test'
import assert from 'node:assert/strict'
import { historyPage, mergeHistory, questionPreviews } from '../src/utils/historyPaging.ts'

test('prepending overlapping pages preserves the exact object used by an active stream', () => {
  const live = { itemId: 'message:999', content: 'partial' }
  const merged = mergeHistory([live], [{ itemId: 'message:1' }, { itemId: 'message:999', content: 'stale' }], true)
  assert.equal(merged.length, 2)
  assert.equal(merged[1], live)
  live.content += ' answer'
  assert.equal(merged[1].content, 'partial answer')
})

test('question rail keeps unloaded previews and orders Snowflake IDs without rounding', () => {
  const index = [
    { messageId: '9007199254740993', question: 'second', answer: 'unloaded answer' },
    { messageId: '9007199254740992', question: 'first', answer: 'old' },
  ]
  const questions = questionPreviews(index, [
    { role: 'user', messageId: '9007199254740992', content: 'first' },
    { role: 'assistant', content: 'updated answer' },
    { role: 'user', itemId: 'local', content: '', image: 'preview' },
  ])
  assert.deepEqual(questions.map(q => q.messageId), ['9007199254740992', '9007199254740993', 'local'])
  assert.equal(questions[0].answer, 'updated answer')
  assert.equal(questions[1].answer, 'unloaded answer')
  assert.equal(questions[2].hasImage, true)
  assert.equal(index[1].answer, 'old')
})

test('page envelope validates responses and still accepts the legacy history array', () => {
  assert.equal(historyPage([]).hasOlder, false)
  assert.equal(historyPage({ items: [], beforeCursor: '9007199254740993', hasOlder: true }).beforeCursor, '9007199254740993')
  assert.throws(() => historyPage({ content: 'bad response' }))
})
