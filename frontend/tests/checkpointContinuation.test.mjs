import test from 'node:test'
import assert from 'node:assert/strict'
import { adoptCheckpointTurn, isContinuationCommand } from '../src/utils/checkpointContinuation.ts'
import { createAgentState } from '../src/utils/agentStream.ts'

test('bare commands are distinct from new requirements and reference payloads', () => {
  for (const text of ['继续', ' 重试！ ', '继续上次任务。', '继续上次未完成任务']) assert.equal(isContinuationCommand(text), true)
  for (const text of ['继续，但改成英文', '继续写第二章', '请解释继续的意思', '继续\n\n<easyjob-writing-context>资料</easyjob-writing-context>']) {
    assert.equal(isContinuationCommand(text), false)
  }
})

test('confirmed recovery replaces the original failed turn without a duplicate command or answer', () => {
  const user = { role: 'user', messageId: 'u1', content: '介绍 Go' }
  const old = { role: 'assistant', messageId: 'old', turnId: 'u1', runId: 'r1', content: '已停止处理。', recoverable: true, agent: createAgentState() }
  old.agent.activities.push({ id: 'search', label: '检索资料', status: 'done' })
  old.agent.status = 'cancelled'
  const command = { role: 'user', content: '继续' }
  const target = { role: 'assistant', content: '', agent: createAgentState() }
  const messages = adoptCheckpointTurn([user, old, command, target], target, [command, target], { runId: 'r1', inputMessageId: 'u1' })
  assert.deepEqual(messages, [user, target])
  assert.equal(target.runId, 'r1')
  assert.equal(target.turnId, 'u1')
  assert.equal(target.agent.status, 'working')
  assert.equal(target.agent.activities[0].status, 'done')
  assert.equal(old.agent.status, 'cancelled')
})

test('recovery button preserves unrelated user turns and clears the old partial answer', () => {
  const user = { role: 'user', content: '原始问题', messageId: 'u' }
  const target = { role: 'assistant', content: '未完成回答', turnId: 'u', runId: 'r', agent: createAgentState(), provisional: true }
  const messages = adoptCheckpointTurn([user, target], target, [target], { runId: 'r' })
  assert.deepEqual(messages, [user, target])
  assert.equal(target.content, '')
  assert.equal(target.provisional, false)
  assert.equal(target.turnId, 'u')
})

test('repeated metadata frames do not duplicate or remove the original question', () => {
  const user = { role: 'user', content: 'q', messageId: 'u' }
  const target = { role: 'assistant', content: '', runId: 'r', turnId: 'u' }
  const payload = { runId: 'r', inputMessageId: 'u' }
  let messages = adoptCheckpointTurn([user, target], target, [target], payload)
  messages = adoptCheckpointTurn(messages, target, [target], payload)
  assert.deepEqual(messages, [user, target])
})

test('a history window without the original turn still keeps one recovered response', () => {
  const command = { role: 'user', content: '继续' }
  const target = { role: 'assistant', content: '' }
  assert.deepEqual(adoptCheckpointTurn([command, target], target, [command, target], { runId: 'r' }), [target])
})
