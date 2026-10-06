/** Cancellation saves work; the identity check also handles transports that ignore abort. */
export function latestRequest() {
  let active: AbortController | undefined
  return {
    begin() {
      active?.abort()
      const controller = new AbortController()
      active = controller
      return { signal: controller.signal, isCurrent: () => active === controller && !controller.signal.aborted }
    },
    cancel() { active?.abort(); active = undefined }
  }
}
