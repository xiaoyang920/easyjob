import test from 'node:test'
import assert from 'node:assert/strict'
import { readWritingConversation, saveWritingConversation, migrateWritingConversation, writingConversationKey } from '../src/utils/writingConversations.ts'

function storage() {
  const values = new Map()
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}
test('writing associations are isolated by account and draft without retaining document content', () => {
  const local = storage()
  assert.equal(saveWritingConversation(local, '7', '42', '101'), true)
  assert.equal(readWritingConversation(local, '7', '42'), '101')
  assert.equal(readWritingConversation(local, '8', '42'), null)
  assert.equal(readWritingConversation(local, '7', '43'), null)
  assert.equal(saveWritingConversation(local, null, '42', '101'), false)
  assert.notEqual(writingConversationKey('7:42', 'new'), writingConversationKey('7', '42:new'))
  saveWritingConversation(local, '7', '42', null)
  assert.equal(readWritingConversation(local, '7', '42'), null)
})
test('first save migrates an unsaved chat and leaves a clean association for the next new draft', () => {
  const local = storage()
  saveWritingConversation(local, '7', 'new', '101')
  assert.equal(migrateWritingConversation(local, '7', 'new', '55', null), true)
  assert.equal(readWritingConversation(local, '7', '55'), '101')
  assert.equal(readWritingConversation(local, '7', 'new'), null)
  saveWritingConversation(local, '7', '55', '102')
  assert.equal(readWritingConversation(local, '7', '55'), '102')
})
test('failed storage migration preserves the recoverable association instead of losing it', () => {
  const local = storage()
  saveWritingConversation(local, '7', 'new', '101')
  local.setItem = () => { throw new Error('quota') }
  assert.equal(migrateWritingConversation(local, '7', 'new', '55', '101'), false)
  assert.equal(readWritingConversation(local, '7', 'new'), '101')
  assert.equal(readWritingConversation({ getItem() { throw new Error('blocked') } }, '7', '42'), null)
})
