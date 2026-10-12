// UI selection never owns execution. Every asynchronous callback keeps its original session.
export interface ChatSession<Message, Image> {
  key: string
  conversationId: string | null
  originArticleId: string | null
  originArticleTitle: string
  messages: Message[]
  userInput: string
  selectedImages: Image[]
  loading: boolean
  streaming: boolean
  resuming: boolean
  cancelling: boolean
  operation: number
  historyLoaded: boolean
  historyLoadFailed: boolean
  abortController: AbortController | null
  unread: boolean
  questionIndex: import('./historyPaging').QuestionPreview[]
  historyWindow: import('./historyPaging').HistoryWindow
  historyBusy: boolean
  historyVersion: number
  questionVersion: number
  questionIndexFailed: boolean
  liveMessages: Message[]
}

export function createChatSession<Message, Image>(key: string, conversationId: string | null = null): ChatSession<Message, Image> {
  return { key, conversationId, originArticleId: null, originArticleTitle: '', messages: [], userInput: '',
    selectedImages: [], loading: false, streaming: false, resuming: false, cancelling: false, operation: 0, historyLoaded: false,
    historyLoadFailed: false, abortController: null, unread: false, questionIndex: [],
    historyWindow: { beforeCursor: null, afterCursor: null, hasOlder: false, hasNewer: false },
    historyBusy: false, historyVersion: 0, questionVersion: 0, questionIndexFailed: false, liveMessages: [] }
}

export function beginChatOperation<Message, Image>(session: ChatSession<Message, Image>): number {
  session.loading = session.streaming = true
  return ++session.operation
}

export function finishChatOperation<Message, Image>(session: ChatSession<Message, Image>, operation: number): boolean {
  // A stopped reader can settle after a new turn starts. It cannot clear the new turn's state.
  if (session.operation !== operation) return false
  session.loading = session.streaming = session.resuming = false
  session.abortController = null
  return true
}

export function bindConversationId<Message, Image>(sessions: Map<string, ChatSession<Message, Image>>, session: ChatSession<Message, Image>, id: string) {
  // A late ID from an inactive stream must be attached to its source, never the selected chat.
  const existing = sessions.get(id)
  if (existing && existing !== session) throw new Error('会话正在同步，请稍后重新进入')
  session.conversationId = id
  sessions.set(id, session)
}

export function releaseChatSessions<Message, Image>(sessions: Iterable<ChatSession<Message, Image>>) {
  // Disconnect only the readers. The durable server run continues until completion or explicit cancel.
  for (const session of new Set(sessions)) {
    session.abortController?.abort()
    session.abortController = null
  }
}
