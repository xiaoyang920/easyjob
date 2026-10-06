import test from 'node:test'
import assert from 'node:assert/strict'
import { EffectiveReadClock } from '../src/utils/effectiveReading.ts'
import { approvalRecovery } from '../src/utils/approvalRecovery.ts'

test('background time does not create an effective read', () => {
  const clock = new EffectiveReadClock(0, true)
  assert.equal(clock.advance(5000, false), false)
  assert.equal(clock.advance(120000, true), false)
  assert.equal(clock.advance(129999, true), false)
  assert.equal(clock.advance(130000, true), true)
  assert.equal(clock.elapsed, 15000)
})
test('initially hidden article needs fifteen visible seconds', () => {
  const clock = new EffectiveReadClock(0, false)
  assert.equal(clock.advance(60000, true), false)
  assert.equal(clock.advance(75000, false), true)
})
test('a committed save closes approval even when the response was lost', () => {
  const state = approvalRecovery({ status: 'succeeded', draftArticleId: '42' })
  assert.equal(state.interrupted, false)
  assert.equal(state.articleId, '42')
  assert.equal(state.status, 'complete')
})
test('expired, cancelled and failed runs never offer another save', () => {
  for (const status of ['expired', 'cancelled', 'failed']) assert.equal(approvalRecovery({ status }).interrupted, false)
})
test('version conflict replaces the approval payload with the server version', () => {
  const payload = { runId: 'r', draftHash: 'new', draft: 'latest' }
  assert.equal(approvalRecovery({ status: 'awaiting_approval', result: { interrupted: payload } }).payload, payload)
})
test('an in-flight approval is replayed and cannot be submitted again', () => {
  const state = approvalRecovery({ status: 'running' })
  assert.equal(state.status, 'working')
  assert.equal(state.interrupted, false)
})
