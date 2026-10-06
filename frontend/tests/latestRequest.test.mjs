import assert from 'node:assert/strict'
import { test } from 'node:test'
import { latestRequest } from '../src/utils/latestRequest.ts'

test('slow old success and error cannot change results or clear the new loading state', async () => {
  const requests = latestRequest()
  const state = { result: '', loading: false, error: '' }
  const pending = []
  function run() {
    const ticket = requests.begin()
    state.loading = true
    const result = new Promise((resolve, reject) => pending.push({ resolve, reject }))
    return { ticket, done: result.then(value => { if(ticket.isCurrent()) state.result = value },
      error => { if(ticket.isCurrent()) state.error = error.message }).finally(() => { if(ticket.isCurrent()) state.loading = false }) }
  }
  const old = run()
  const newer = run()
  assert.equal(old.ticket.signal.aborted, true)
  pending[0].resolve('stale')
  await old.done
  assert.deepEqual(state, { result: '', loading: true, error: '' })
  pending[1].resolve('current')
  await newer.done
  assert.deepEqual(state, { result: 'current', loading: false, error: '' })
  const failing = run()
  const latest = run()
  pending[2].reject(new Error('stale error'))
  await failing.done
  assert.equal(state.error, '')
  assert.equal(state.loading, true)
  pending[3].reject(new Error('current error'))
  await latest.done
  assert.equal(state.error, 'current error')
  assert.equal(state.loading, false)
})

test('leaving a page invalidates in-flight requests and allows a later request', () => {
  const requests = latestRequest()
  const first = requests.begin()
  requests.cancel()
  assert.equal(first.signal.aborted, true)
  assert.equal(first.isCurrent(), false)
  assert.equal(requests.begin().isCurrent(), true)
})
