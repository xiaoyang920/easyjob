import type { AgentStreamState } from './agentStream'

export function isContinuationCommand(content: string): boolean {
  return /^(?:继续|重试|继续上次任务|继续上次未完成任务)[。.!！\s]*$/u.test(content.trim())
}

interface ContinuationMessage {
  role: 'user' | 'assistant'
  content: string
  runId?: string
  turnId?: string
  messageId?: string
  recoverable?: boolean
  provisional?: boolean
  agent?: AgentStreamState
}

// A server-confirmed continuation updates the original turn. The command and
// placeholder are transient; neither is a new message in durable chat history.
export function adoptCheckpointTurn<T extends ContinuationMessage>(
  messages: T[], target: T, liveMessages: T[], payload: { runId: string; inputMessageId?: string | null },
): T[] {
  if (typeof payload.runId !== 'string' || !payload.runId) throw new Error('恢复任务标识缺失')
  const previous = [...messages].reverse().find(item => item.role === 'assistant' && item.runId === payload.runId) || target
  target.runId = payload.runId
  target.turnId = payload.inputMessageId || previous.turnId
  target.messageId = previous.messageId
  target.recoverable = false
  target.provisional = false
  target.content = ''
  if (previous.agent) {
    target.agent = { ...previous.agent, status: 'working', startedAt: Date.now(), finishedAt: undefined,
      answerSequence: 0, answerReceiving: false, commentary: [...previous.agent.commentary],
      activities: previous.agent.activities.map(item => ({ ...item })),
      plan: previous.agent.plan.map(item => ({ ...item })) }
  }
  return messages.flatMap(item => {
    if (item === previous) return [target]
    if ((item === target && previous !== target)
        || (item.role === 'user' && liveMessages.includes(item))) return []
    return [item]
  })
}
