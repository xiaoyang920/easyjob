/** Only a first answer actually seen during this submission is a timing sample. */
export function createDeliveryTiming(doc: Document, now: () => number = () => performance.now()) {
  const started = now()
  let eligible = doc.visibilityState === 'visible', consumed = false
  const changed = () => { if (doc.visibilityState !== 'visible') eligible = false }
  doc.addEventListener('visibilitychange', changed)
  return {
    sample(answerVisible: boolean): number | null {
      if (consumed) return null
      consumed = true
      if (!eligible || !answerVisible || doc.visibilityState !== 'visible') return null
      return Math.max(0, Math.round(now() - started))
    },
    invalidate() { eligible = false },
    dispose() { doc.removeEventListener('visibilitychange', changed) },
  }
}
