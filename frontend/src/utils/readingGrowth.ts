export type ReadingProgress = {
  level: number; totalSeconds: number; nextLevel: number | null; secondsToNext: number;
  rules: { level: number; minSeconds: number }[];
}
export type ReadingBeat = { sessionId: string; sequence: number; active: boolean }

/** Retries reuse the same sequence, even when the server committed a timed-out request. */
export class ReadingHeartbeatPump {
  private pending: ReadingBeat | undefined
  private sequence = 0
  private busy = false
  private stopped = false
  private active: boolean
  private lastSent: number
  private sessionId: string
  private send: (beat: ReadingBeat) => Promise<ReadingProgress>
  private received: (progress: ReadingProgress) => void
  private failed: (error: unknown) => boolean
  constructor(sessionId: string, active: boolean, now: number,
    send: (beat: ReadingBeat) => Promise<ReadingProgress>,
    received: (progress: ReadingProgress) => void,
    failed: (error: unknown) => boolean) {
    this.sessionId = sessionId; this.send = send; this.received = received; this.failed = failed
    this.active = active; this.lastSent = now
  }
  async update(active: boolean, now: number) {
    if (this.stopped || this.busy) return
    if (!this.pending && this.active === active && now - this.lastSent < 15000) return
    this.pending ??= { sessionId: this.sessionId, sequence: this.sequence + 1, active }
    const request = this.pending
    this.busy = true
    try {
      const progress = await this.send({ ...request })
      this.sequence = request.sequence; this.active = request.active; this.lastSent = now; this.pending = undefined
      if (!this.stopped) this.received(progress)
    } catch (error) { if (this.failed(error)) this.stopped = true }
    finally { this.busy = false }
  }
  stop() { this.stopped = true }
}

export function readingDuration(seconds: number) {
  if (seconds < 60) return `${Math.max(0, Math.ceil(seconds))} 秒`
  const minutes = Math.ceil(seconds / 60)
  return minutes < 60 ? `${minutes} 分钟` : `${Math.floor(minutes / 60)} 小时${minutes % 60 ? ` ${minutes % 60} 分钟` : ''}`
}
