export interface ContextUsage {
  scope: 'main_request'
  estimated: true
  usedTokens: number | null
  limitTokens: number
  inputBudgetTokens: number
  measuredAt: string | null
}

export function parseContextUsage(raw: unknown): ContextUsage | null {
  if (!raw || typeof raw !== 'object') return null
  const value = raw as Record<string, unknown>
  const integer = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0
  if (value.scope !== 'main_request' || value.estimated !== true || !integer(value.limitTokens) || !value.limitTokens ||
      !integer(value.inputBudgetTokens) || (value.usedTokens !== null && !integer(value.usedTokens))) return null
  return { scope: 'main_request', estimated: true, usedTokens: value.usedTokens as number | null,
    limitTokens: value.limitTokens, inputBudgetTokens: value.inputBudgetTokens,
    measuredAt: typeof value.measuredAt === 'string' ? value.measuredAt : null }
}

export function contextPercent(usage: ContextUsage | null): number | null {
  return usage?.usedTokens == null ? null : Math.min(100, Math.max(0, Math.round(usage.usedTokens / usage.limitTokens * 100)))
}

export function formatContextTokens(tokens: number): string {
  return tokens < 1024 ? String(tokens) : `${Number((tokens / 1024).toFixed(1))}k`
}
