/** Accumulate foreground time only; hidden tabs and failed article loads do not count. */
export class EffectiveReadClock {
  elapsed = 0
  private last: number
  private visible: boolean
  private threshold: number
  constructor(now: number, visible: boolean, threshold = 15000) { this.last = now; this.visible = visible; this.threshold = threshold }
  advance(now: number, visible: boolean) {
    if (this.visible) this.elapsed += Math.max(0, now - this.last)
    this.last = now
    this.visible = visible
    return this.elapsed >= this.threshold
  }
}

export function trackEffectiveReading(onRead: () => void) {
  const clock = new EffectiveReadClock(performance.now(), !document.hidden)
  let stopped = false
  const check = () => {
    if (!stopped && clock.advance(performance.now(), !document.hidden)) { stop(); onRead() }
  }
  const timer = setInterval(check, 1000)
  const stop = () => { stopped = true; clearInterval(timer); document.removeEventListener('visibilitychange', check) }
  document.addEventListener('visibilitychange', check)
  return stop
}
