import assert from 'node:assert/strict'
import { test } from 'node:test'
import { build } from 'esbuild'

const source = (await build({ entryPoints: ['src/utils/authSession.ts'], bundle: true, write: false,
  format: 'esm', platform: 'node' })).outputFiles[0].text
let sequence = 0
const token = seconds => 'header.' + btoa(JSON.stringify({ exp: Date.now() / 1000 + seconds })) + '.signature'
async function fixture(handler) {
  const values = new Map([['token', token(1800)], ['userId', '7']])
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key), key: i => [...values.keys()][i] ?? null, get length() { return values.size } }
  globalThis.fetch = handler
  const module = await import('data:text/javascript;base64,' + Buffer.from(source + '\n// fixture ' + (++sequence)).toString('base64'))
  return { values, ...module }
}
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

test('401 stream handshake renews once and retries with identical task body', async () => {
  const requests = []
  const renewed = token(1900)
  const auth = await fixture(async (url, init) => {
    requests.push({ url, init })
    if (url.includes('refresh')) return json({ code: 200, data: { token: renewed, userId: '7' } })
    if (requests.length === 1) return json({ code: 401 }, 401)
    return new Response('data:final answer\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
  })
  const body = JSON.stringify({ message: 'test', requestId: 'same-task-id' })
  const result = await auth.authenticatedFetch('/api/agent/chat/stream', { method: 'POST', body })
  assert.equal(result.status, 200)
  assert.equal(requests.length, 3)
  assert.equal(requests[0].init.body, requests[2].init.body)
  assert.equal(requests[2].init.headers.get('Authorization'), 'Bearer ' + renewed)
})

test('second 401 never loops and clears only the rejected current account', async () => {
  let calls = 0
  const auth = await fixture(async url => {
    calls++
    return url.includes('refresh') ? json({ code: 200, data: { token: token(1900), userId: '7' } }) : json({ code: 401 }, 401)
  })
  const response = await auth.authenticatedFetch('/api/agent/chat/stream', { method: 'POST', body: '{}' })
  assert.equal(response.status, 401)
  assert.equal(calls, 3)
  assert.equal(auth.values.get('token'), undefined)
})

test('refresh 503 keeps login state and does not replay the task', async () => {
  let requests = 0
  const auth = await fixture(async url => {
    if (url.includes('refresh')) return json({ code: 503, message: 'service unavailable' }, 503)
    requests++
    return json({ code: 401 }, 401)
  })
  const before = auth.values.get('token')
  await assert.rejects(auth.authenticatedFetch('/api/agent/chat/stream', { method: 'POST' }), /service unavailable/)
  assert.equal(requests, 1)
  assert.equal(auth.values.get('token'), before)
})

test('successful stream is opened once without background replay', async () => {
  let calls = 0
  const auth = await fixture(async () => { calls++; return new Response('data:answer\n\n') })
  const response = await auth.authenticatedFetch('/api/agent/chat/stream', { method: 'POST' })
  assert.equal(await response.text(), 'data:answer\n\n')
  assert.equal(calls, 1)
})

test('old account 401 cannot replay task under a different account', async () => {
  let calls = 0, auth
  auth = await fixture(async () => {
    calls++; auth.values.set('token', 'other-login'); auth.values.set('userId', '8')
    return json({ code: 401 }, 401)
  })
  const response = await auth.authenticatedFetch('/api/agent/chat/stream', { method: 'POST' })
  assert.equal(response.status, 401)
  assert.equal(calls, 1)
  assert.equal(auth.values.get('token'), 'other-login')
})

test('registration installs a complete identity without a second login and keeps isolated search histories', async () => {
  const auth = await fixture(() => { throw new Error('automatic login must not make another request') })
  auth.values.set('avatar', '/old-account.png')
  auth.values.set('private-draft', 'old account only')
  auth.values.set('easyjob:search-history:v1:user:7', '["Redis"]')
  auth.acceptAuthSession({ token: token(3600), userId: '9007199254740993', email: 'new@example.invalid', nickName: '新读者', avatar: null })
  assert.equal(auth.values.get('userId'), '9007199254740993')
  assert.equal(auth.values.get('email'), 'new@example.invalid')
  assert.equal(auth.values.get('nickName'), '新读者')
  assert.equal(auth.values.get('avatar'), '')
  assert.equal(auth.values.get('private-draft'), undefined)
  assert.equal(auth.values.get('easyjob:search-history:v1:user:7'), '["Redis"]')
  assert.equal(await auth.ensureAccessToken(), auth.values.get('token'))
})

test('an incomplete registration response cannot replace the current login identity', async () => {
  const auth = await fixture(() => { throw new Error('unexpected request') })
  const before = [...auth.values]
  for (const data of [undefined, {}, { token: '', userId: '8' }, { token: 'token', userId: '' }])
    assert.throws(() => auth.acceptAuthSession(data), /登录信息不完整/)
  assert.deepEqual([...auth.values], before)
})
