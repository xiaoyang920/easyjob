import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAuthRenewal, tokenExpiresSoon } from '../src/utils/authRenewal.ts'

const jwt = exp => 'header.' + btoa(JSON.stringify({ exp })) + '.signature'
function fixture(renew) {
  const state = { token: jwt(1), user: '7' }
  return { state, auth: createAuthRenewal({ token: () => state.token, user: () => state.user,
    save: token => { state.token = token }, renew }) }
}

test('parallel API/SSE/upload requests share exactly one refresh', async () => {
  let finish, calls = 0
  const { state, auth } = fixture(() => { calls++; return new Promise(resolve => { finish = resolve }) })
  const requests = Array.from({ length: 8 }, () => auth.ensure())
  assert.equal(calls, 1)
  finish({ token: jwt(Date.now() / 1000 + 1800), userId: '7' })
  const tokens = await Promise.all(requests)
  assert.equal(new Set(tokens).size, 1)
  assert.equal(tokens[0], state.token)
})

test('logout while refresh is pending never restores login', async () => {
  let finish
  const { state, auth } = fixture(() => new Promise(resolve => { finish = resolve }))
  const request = auth.ensure()
  state.token = null; state.user = null
  finish({ token: 'stale', userId: '7' })
  assert.equal(await request, null)
  assert.equal(state.token, null)
})

test('old refresh cannot overwrite another account login', async () => {
  let finish
  const { state, auth } = fixture(() => new Promise(resolve => { finish = resolve }))
  const request = auth.ensure()
  state.token = 'new-login'; state.user = '8'
  finish({ token: 'old-refresh', userId: '7' })
  assert.equal(await request, null)
  assert.equal(state.token, 'new-login')
})

test('network failures retain credentials and allow the next retry', async () => {
  let calls = 0
  const { state, auth } = fixture(async () => {
    if (++calls === 1) throw new Error('offline')
    return { token: 'renewed', userId: '7' }
  })
  const before = state.token
  await assert.rejects(auth.ensure(), /offline/)
  assert.equal(state.token, before)
  assert.equal(await auth.ensure(), 'renewed')
  assert.equal(calls, 2)
})

test('healthy tokens and guests do not refresh; margin is 60 seconds', async () => {
  assert.equal(tokenExpiresSoon(jwt(200), 139000), false)
  assert.equal(tokenExpiresSoon(jwt(200), 140000), true)
  const { state, auth } = fixture(async () => { throw new Error('should not refresh') })
  state.token = jwt(Date.now() / 1000 + 300)
  assert.equal(await auth.ensure(), state.token)
  state.token = null
  assert.equal(await auth.ensure(true), null)
})

test('different refresh principal cannot silently change account', async () => {
  const { state, auth } = fixture(async () => ({ token: 'other', userId: '8' }))
  const before = state.token
  await assert.rejects(auth.ensure(), /账号不一致/)
  assert.equal(state.token, before)
})
