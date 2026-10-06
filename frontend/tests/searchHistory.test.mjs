import test from 'node:test'
import assert from 'node:assert/strict'
import { SEARCH_HISTORY_PREFIX, searchHistoryKey, readSearchHistory, rememberSearch, deleteSearch, clearSearchHistory, clearAccountStorage } from '../src/utils/searchHistory.ts'

class MemoryStorage {
  values = new Map()
  get length() { return this.values.size }
  key(index) { return [...this.values.keys()][index] ?? null }
  getItem(key) { return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(key, String(value)) }
  removeItem(key) { this.values.delete(key) }
}

test('submitted searches are trimmed, deduplicated and moved to the front', () => {
  const store = new MemoryStorage()
  rememberSearch(' RAG ', store)
  rememberSearch('Redis', store)
  assert.deepEqual(rememberSearch('rag', store), ['rag', 'Redis'])
  assert.deepEqual(rememberSearch('   ', store), ['rag', 'Redis'])
})

test('history retains only the ten most recent submitted searches across reloads', () => {
  const store = new MemoryStorage()
  for (let i = 0; i < 15; i++) rememberSearch('query ' + i, store)
  assert.deepEqual(readSearchHistory(store), Array.from({length:10}, (_, i) => 'query ' + (14 - i)))
})

test('guest and different signed-in accounts have independent histories', () => {
  const store = new MemoryStorage()
  rememberSearch('guest query', store)
  store.setItem('token', 'fixture-token')
  store.setItem('userId', '1')
  rememberSearch('account one', store)
  store.setItem('userId', '2')
  assert.deepEqual(readSearchHistory(store), [])
  rememberSearch('account two', store)
  store.setItem('userId', '1')
  assert.deepEqual(readSearchHistory(store), ['account one'])
  store.removeItem('token')
  assert.deepEqual(readSearchHistory(store), ['guest query'])
})

test('single deletion and clear affect only the current account', () => {
  const store = new MemoryStorage()
  rememberSearch('guest', store)
  store.setItem('token', 'fixture-token')
  store.setItem('userId', '1')
  rememberSearch('RAG', store)
  rememberSearch('Redis', store)
  assert.deepEqual(deleteSearch('rag', store), ['Redis'])
  clearSearchHistory(store)
  assert.deepEqual(readSearchHistory(store), [])
  store.removeItem('token')
  assert.deepEqual(readSearchHistory(store), ['guest'])
})

test('malformed, duplicate and oversized saved entries cannot break the dropdown', () => {
  const store = new MemoryStorage()
  store.setItem(searchHistoryKey(store), 'not json')
  assert.deepEqual(readSearchHistory(store), [])
  store.setItem(searchHistoryKey(store), JSON.stringify([null, {}, 42, ' ', 'RAG', 'rag', ' Redis ', 'x'.repeat(201)]))
  assert.deepEqual(readSearchHistory(store), ['RAG', 'Redis'])
  assert.deepEqual(rememberSearch('x'.repeat(201), store), ['RAG', 'Redis'])
})

test('blocked browser storage never prevents a search or removal', () => {
  const blocked = {getItem(){throw Error('blocked')},setItem(){throw Error('blocked')},removeItem(){throw Error('blocked')}}
  assert.deepEqual(readSearchHistory(blocked), [])
  assert.deepEqual(rememberSearch('RAG', blocked), ['RAG'])
  assert.doesNotThrow(() => deleteSearch('RAG', blocked))
  assert.doesNotThrow(() => clearSearchHistory(blocked))
})

test('login cleanup removes credentials but preserves account and guest search history', () => {
  const store = new MemoryStorage()
  rememberSearch('guest', store)
  store.setItem('token', 'fixture-token')
  store.setItem('userId', '1')
  rememberSearch('private account query', store)
  store.setItem('avatar', '/fixture-avatar.png')
  clearAccountStorage(store)
  assert.equal(store.getItem('token'), null)
  assert.equal(store.getItem('userId'), null)
  assert.equal(store.getItem('avatar'), null)
  assert.deepEqual(readSearchHistory(store), ['guest'])
  store.setItem('token', 'fixture-token')
  store.setItem('userId', '1')
  assert.deepEqual(readSearchHistory(store), ['private account query'])
  assert.equal([...store.values.keys()].filter(key => key.startsWith(SEARCH_HISTORY_PREFIX)).length, 2)
})
