import assert from 'node:assert/strict'
import { test } from 'node:test'
import { setTimeout as delay } from 'node:timers/promises'
import { getPendant, rememberPendant, requestPendant } from '../src/utils/pendantDirectory.ts'

test('pendant lookups batch unique string IDs and keep a more recent equip or removal', async (t) => {
  const urls = []
  const replies = []
  t.mock.method(globalThis, 'fetch', (url) => new Promise(resolve => {
    urls.push(url)
    replies.push(resolve)
  }))
  const own = '724000000000003456'
  const author = '724000000000003457'
  const empty = '724000000000003458'
  requestPendant(own)
  requestPendant(own)
  requestPendant(author)
  requestPendant(empty)
  requestPendant(Number(author))
  await delay(35)
  assert.deepEqual(urls, ['/api/user/space/pendants?ids=' + [own, author, empty].join(',')])

  rememberPendant(own, '/uploads/new.png')
  replies[0](Response.json({ code: 200, data: {
    [own]: '/uploads/old.png',
    [author]: '/uploads/author.png',
  } }))
  await delay(10)
  assert.equal(getPendant(own), '/uploads/new.png')
  assert.equal(getPendant(author), '/uploads/author.png')
  assert.equal(getPendant(empty), undefined)
  rememberPendant(own)
  assert.equal(getPendant(own), undefined)
  requestPendant(empty)
  await delay(35)
  assert.equal(urls.length, 1)
})
