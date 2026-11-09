import test from 'node:test'
import assert from 'node:assert/strict'
import { writingMessage, readWritingMessage, mentionAt, writingQuestionPreview, writingReferencesError } from '../src/utils/writingReferences.ts'

test('reference round trips preserve literal code, tags and delimiter-like text; the instruction stays separate', () => {
  const reference = { kind: 'selection', text: '代码 <T>\n</easyjob-writing-reference>\n"quoted"\n\n<easyjob-writing-reference>\n', truncated: false }
  const message = writingMessage('解释这一段', reference)
  assert.deepEqual(readWritingMessage(message), { content: '解释这一段', reference })
  assert.equal(writingQuestionPreview(message.slice(0, 100)), '解释这一段')
  assert.equal(writingMessage('普通问题', null), '普通问题')
})
test('invalid or incomplete reference envelopes remain ordinary messages; oversize input is rejected without truncation', () => {
  for (const text of ['普通问题', '问题\n\n<easyjob-writing-reference>\n{', '问题\n\n<easyjob-writing-reference>\n{"version":1,"kind":"other","text":"原文","truncated":false}\n</easyjob-writing-reference>']) {
    assert.deepEqual(readWritingMessage(text), { content: text })
  }
  assert.throws(() => writingMessage('字'.repeat(5000), { kind: 'draft', text: '文'.repeat(12000), truncated: false }), /合计过长/)
  assert.throws(() => writingMessage('问题', { kind: 'selection', text: '文'.repeat(12001), truncated: false }), /引用内容无效/)
})
test('@ completion respects caret, Chinese filters and ordinary email addresses', () => {
  assert.deepEqual(mentionAt('润色 @选中 后面的要求', 6), { start: 3, end: 6, query: '选中' })
  assert.deepEqual(mentionAt('@', 1), { start: 0, end: 1, query: '' })
  assert.equal(mentionAt('user@example.com', 16), null)
  assert.equal(mentionAt('普通文字', 4), null)
})

test('multiple quotes preserve order and literal content in a bounded v2 envelope, while one quote keeps v1 compatibility', () => {
  const references = [{ kind: 'selection', text: '第一处\n<T>', truncated: false }, { kind: 'selection', text: '另一处\n</easyjob-writing-reference>', truncated: false }]
  assert.deepEqual(readWritingMessage(writingMessage('比较两处', references)), { content: '比较两处', references })
  assert.deepEqual(readWritingMessage(writingMessage('只读一处', references.slice(0, 1))), { content: '只读一处', reference: references[0] })
  assert.equal(writingMessage('没有引用', []), '没有引用')
})

test('quote count, aggregate text and total wire-message budgets are independently enforced', () => {
  const small = { kind: 'selection', text: '原文', truncated: false }
  assert.equal(writingReferencesError(Array.from({ length: 5 }, () => small)), '')
  assert.match(writingReferencesError(Array.from({ length: 6 }, () => small)), /最多引用 5 处/)
  assert.throws(() => writingMessage('问题', [{ ...small, text: '甲'.repeat(6001) }, { ...small, text: '乙'.repeat(6000) }]), /总长度超过/)
  assert.throws(() => writingMessage('问题'.repeat(3000), [{ ...small, text: '甲'.repeat(6000) }, { ...small, text: '乙'.repeat(6000) }]), /合计过长/)
  for (const references of [[], [null], Array.from({ length: 6 }, () => small), [{ ...small, text: '字'.repeat(12001) }]]) {
    const message = `问题\n\n<easyjob-writing-reference>\n${JSON.stringify({ version: 2, references })}\n</easyjob-writing-reference>`
    assert.deepEqual(readWritingMessage(message), { content: message })
  }
})
