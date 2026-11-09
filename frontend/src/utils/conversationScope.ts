export type ConversationScope = 'general' | 'article' | 'writing'
export interface ConversationSource { isWriting?: boolean | number | string; originArticleId?: string | null; writingArticleId?: string | null; writingArticleTitle?: string; writingArticleAvailable?: boolean }
export function conversationScope(source: ConversationSource): ConversationScope {
  return source.isWriting === true || Number(source.isWriting) === 1 ? 'writing' : source.originArticleId ? 'article' : 'general'
}
export function conversationCategory(source: ConversationSource) {
  return { general: '普通聊天', article: '文章问答', writing: '草稿写作' }[conversationScope(source)]
}
export function writingSourceTitle(source: ConversationSource) {
  return source.writingArticleTitle || (source.writingArticleId ? '草稿暂不可用' : '未保存草稿')
}
