type TraceHeaders = Headers | Record<string, unknown>

export function traceIdFrom(headers?: TraceHeaders): string | undefined {
  const value = headers instanceof Headers ? headers.get('X-Trace-Id') : headers?.['x-trace-id']
  return typeof value === 'string' && /^[0-9a-f]{32}$/i.test(value) && !/^0+$/.test(value)
    ? value.toLowerCase()
    : undefined
}

export function traceErrorMessage(message: string, traceId?: string): string {
  return traceId ? `${message}（追踪编号 ${traceId}）` : message
}
