import test from 'node:test'
import assert from 'node:assert/strict'
import { ReadingHeartbeatPump, readingDuration } from '../src/utils/readingGrowth.ts'
const progress = { level: 0, totalSeconds: 15, nextLevel: 1, secondsToNext: 3585, rules: [] }

test('a committed but timed-out heartbeat is retried with the same payload and sequence', async () => {
  const requests = []
  const pump = new ReadingHeartbeatPump('session', true, 0, async beat => {
    requests.push(beat); if (requests.length === 1) throw new Error('timeout'); return progress
  }, () => {}, () => false)
  await pump.update(true, 15000)
  await pump.update(false, 20000)
  assert.deepEqual(requests[0], requests[1])
  await pump.update(false, 20001)
  assert.equal(requests[2].sequence, 2); assert.equal(requests[2].active, false)
})
test('pause and resume send immediately but ordinary heartbeats are spaced apart', async () => {
  const requests = []
  const pump = new ReadingHeartbeatPump('session', true, 0, async beat => { requests.push(beat); return progress }, () => {}, () => false)
  await pump.update(true, 1000); assert.equal(requests.length, 0)
  await pump.update(false, 2000); await pump.update(true, 3000)
  assert.deepEqual(requests.map(r => r.active), [false, true])
  await pump.update(true, 17000); assert.equal(requests.length, 2)
  await pump.update(true, 18000); assert.equal(requests.length, 3)
})
test('single in-flight request and ownership loss stop additional heartbeats', async () => {
  let release; let calls = 0
  const pump = new ReadingHeartbeatPump('session', true, 0, async () => { calls++; await new Promise(r => { release = r }); throw new Error('session replaced') }, () => {}, () => true)
  const pending = pump.update(true, 15000)
  await pump.update(true, 16000); assert.equal(calls, 1)
  release(); await pending; await pump.update(true, 30000); assert.equal(calls, 1)
})
test('duration display handles sub-minute time and hours', () => {
  assert.equal(readingDuration(15), '15 秒'); assert.equal(readingDuration(3660), '1 小时 1 分钟')
})
