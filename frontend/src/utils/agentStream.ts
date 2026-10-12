export type ActivityStatus = 'pending' | 'active' | 'done' | 'paused' | 'error'
export type RunStatus = 'working' | 'complete' | 'awaiting' | 'cancelled' | 'error'

export interface AgentActivityItem {
  id: string
  label: string
  status: ActivityStatus
  detail?: string
  actor?: string
  taskId?: string
  startedAt?: number
  finishedAt?: number
}

export interface AgentPlanTask {
  id: string
  label: string
  role: string
  stage: number
  status: ActivityStatus
}

export interface AgentStreamState {
  status: RunStatus
  startedAt: number
  finishedAt?: number
  richEvents: boolean
  commentary: string[]
  activities: AgentActivityItem[]
  plan: AgentPlanTask[]
  answerSequence: number
  answerReceiving: boolean
}

export function createAgentState(): AgentStreamState {
  return { status: 'working', startedAt: Date.now(), richEvents: false, commentary: [],
    activities: [], plan: [], answerSequence: 0, answerReceiving: false }
}

export function setRunStatus(state: AgentStreamState, status: RunStatus) {
  state.status = status
  if (status !== 'working') {
    state.finishedAt = Date.now()
    state.answerReceiving = false
    for (const item of [...state.activities, ...state.plan]) {
      if (item.status === 'active' || item.status === 'pending') {
        item.status = status === 'complete' ? 'done' : status === 'error' ? 'error' : 'paused'
      }
    }
  } else {
    state.startedAt = Date.now()
    state.finishedAt = undefined
  }
}

export function applyAgentEvent(state: AgentStreamState, event: Record<string, any>) {
  if (event.version !== 1) return
  if (!state.richEvents) state.activities = [] // Replace legacy progress once rich events arrive.
  state.richEvents = true
  if (event.kind === 'commentary' && typeof event.text === 'string') {
    if (state.commentary.at(-1) !== event.text) state.commentary.push(event.text.slice(0, 500))
  } else if (event.kind === 'plan' && Array.isArray(event.tasks)) {
    const previous = new Map(state.plan.map(task => [task.id, task]))
    const next = event.tasks.map((task: any): AgentPlanTask => ({ id: String(task.id), label: String(task.label).slice(0, 120),
      role: String(task.role), stage: Number(task.stage), status: previous.get(task.id)?.status || 'pending' }))
    // Incremental plans retain already completed work in the activity panel.
    const ids = new Set(next.map((task: AgentPlanTask) => task.id))
    state.plan = [...state.plan.filter(task => !ids.has(task.id)), ...next]
  } else if (event.kind === 'activity' && typeof event.id === 'string' && typeof event.label === 'string') {
    if (!['active', 'done', 'paused', 'error'].includes(event.status)) return
    const timestamp = typeof event.timestamp === 'string' ? Date.parse(event.timestamp) : NaN
    const now = Number.isFinite(timestamp) ? timestamp : Date.now()
    let item = state.activities.find(item => item.id === event.id)
    if (!item) {
      item = { id: event.id, label: event.label, status: event.status, startedAt: now }
      state.activities.push(item)
    }
    if (event.status === 'active' && item.status !== 'active') {
      item.startedAt = now
      item.finishedAt = undefined
    }
    Object.assign(item, { label: event.label.slice(0, 120), status: event.status,
      detail: typeof event.detail === 'string' ? event.detail.slice(0, 500) : '', actor: event.actor, taskId: event.taskId })
    if (event.status !== 'active') item.finishedAt = now
    const task = state.plan.find(task => task.id === event.taskId)
    if (task) {
      if (event.step === 'task' || event.step === 'save_draft' || event.step === 'reject_draft') task.status = event.status
      else if (event.status === 'error') task.status = 'error'
      else if (event.status === 'paused') task.status = 'paused'
      else if (event.status === 'active') task.status = 'active'
    }
  } else if (event.kind === 'status' && ['working', 'complete', 'awaiting', 'cancelled', 'error'].includes(event.status)) {
    setRunStatus(state, event.status)
  }
}

export function restoreAgentState(message: Record<string, any>): AgentStreamState | undefined {
  if (!message.runStatus) return undefined
  const state = createAgentState()
  for (const event of message.agentEvents || []) applyAgentEvent(state, event)
  const status: RunStatus = ({ failed: 'error', expired: 'error', cancelled: 'cancelled',
    succeeded: 'complete', awaiting_approval: 'awaiting' } as Record<string, RunStatus>)[message.runStatus] || 'working'
  setRunStatus(state, status)
  const started = Date.parse(message.runStartedAt || '')
  const finished = Date.parse(message.runFinishedAt || '')
  if (Number.isFinite(started)) state.startedAt = started
  if (Number.isFinite(finished)) state.finishedAt = finished
  return state
}

export function applyAnswerChunk(state: AgentStreamState, content: string, event: Record<string, any>): string {
  if (event.type === 'start') {
    state.answerSequence = 0
    state.answerReceiving = true
    return ''
  }
  if (event.type === 'delta') {
    if (!state.answerReceiving || !Number.isInteger(event.seq) || typeof event.content !== 'string') throw new Error('答案数据不完整')
    if (event.seq < state.answerSequence) return content
    if (event.seq !== state.answerSequence) throw new Error('答案分段顺序不正确')
    state.answerSequence++
    return content + event.content
  }
  if (event.type === 'end') {
    if (event.chunks !== state.answerSequence) throw new Error('答案数据不完整')
    state.answerReceiving = false
  }
  return content
}

export class SseDecoder {
  private buffer = ''
  push(text: string): string[] {
    this.buffer += text
    const frames = this.buffer.split(/\r?\n\r?\n/)
    this.buffer = frames.pop() || ''
    return frames.map(frame => this.parse(frame)).filter((data): data is string => data !== null)
  }
  finish(): string[] {
    const data = this.parse(this.buffer)
    this.buffer = ''
    return data === null ? [] : [data]
  }
  private parse(frame: string): string | null {
    const lines = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
    return lines.length ? lines.map(line => line.slice(5).replace(/^ /, '')).join('\n') : null
  }
}

export async function* readSse(response: Response): AsyncGenerator<string> {
  if (!response.ok) {
    let message = response.status === 409
      ? '草稿版本或运行状态已改变，请重新加载会话后操作'
      : `请求失败：${response.status}`
    try {
      const body = await response.json()
      if (typeof body.message === 'string' && body.message.trim()) message = body.message
      else if (typeof body.detail === 'string' && body.detail.trim()) message = body.detail
    } catch { /* A proxy may return an empty or non-JSON error body. */ }
    throw Object.assign(new Error(message), { status: response.status })
  }
  if (!response.body) throw new Error('没有收到响应内容')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const frames = new SseDecoder()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      for (const data of frames.push(decoder.decode(value, { stream: true }))) yield data
    }
    for (const data of frames.push(decoder.decode())) yield data
    for (const data of frames.finish()) yield data
  } finally {
    reader.releaseLock()
  }
}
