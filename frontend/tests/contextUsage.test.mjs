import test from 'node:test'
import assert from 'node:assert/strict'
import { parseContextUsage, contextPercent, formatContextTokens } from '../src/utils/contextUsage.ts'
import { createAgentState, applyAgentEvent } from '../src/utils/agentStream.ts'

const raw = { scope: 'main_request', estimated: true, usedTokens: 65536, limitTokens: 262144, inputBudgetTokens: 245760 }
test('context measurement handles unknown, limits and malformed payloads', () => {
  assert.equal(contextPercent(parseContextUsage(raw)), 25)
  assert.equal(contextPercent(parseContextUsage({ ...raw, usedTokens: null })), null)
  assert.equal(contextPercent(parseContextUsage({ ...raw, usedTokens: 0 })), 0)
  assert.equal(contextPercent(parseContextUsage({ ...raw, usedTokens: 300000 })), 100)
  for (const bad of [null, {}, { ...raw, limitTokens: 0 }, { ...raw, usedTokens: -1 }, { ...raw, usedTokens: '65536' }])
    assert.equal(parseContextUsage(bad), null)
  assert.equal(formatContextTokens(262144), '256k')
})
test('restoring usage telemetry never clears activities or creates progress', () => {
  const state = createAgentState()
  state.activities.push({ id: 'old', label: '已完成', status: 'done' })
  applyAgentEvent(state, { version: 1, kind: 'context_usage', usage: raw })
  assert.equal(state.richEvents, false)
  assert.equal(state.activities.length, 1)
})
