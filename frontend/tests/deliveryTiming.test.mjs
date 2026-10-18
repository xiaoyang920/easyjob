import test from 'node:test'
import assert from 'node:assert/strict'
import { createDeliveryTiming } from '../src/utils/deliveryTiming.ts'

function fixture() {
  const doc = new EventTarget(); doc.visibilityState = 'visible'
  let now = 100
  return { doc, timing: createDeliveryTiming(doc, () => now), advance: () => { now = 1350 } }
}
test('visible first answer includes elapsed time and is measured once', () => {
  const { timing, advance } = fixture(); advance()
  assert.equal(timing.sample(true), 1250); assert.equal(timing.sample(true), null); timing.dispose()
})
test('hidden tabs and replay are never counted as zero or late samples', () => {
  for (const reason of ['hidden', 'replay', 'offscreen']) {
    const { doc, timing, advance } = fixture(); advance()
    if (reason === 'hidden') { doc.visibilityState = 'hidden'; doc.dispatchEvent(new Event('visibilitychange')); doc.visibilityState = 'visible' }
    if (reason === 'replay') timing.invalidate()
    assert.equal(timing.sample(reason !== 'offscreen'), null)
    assert.equal(timing.sample(true), null); timing.dispose()
  }
})
