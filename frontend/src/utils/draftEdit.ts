export interface DraftEdit { title: string; summary: string; content: string; content_format?: 'markdown' | 'html' }

export function draftEditFrom(payload: Record<string, any>, content = ''): DraftEdit {
  return { title: String(payload.title || ''), summary: String(payload.summary || ''), content: String(payload.draft ?? content),
    ...(payload.contentFormat === 'html' ? { content_format: 'html' as const } : {}) }
}

export function draftEditError(draft: DraftEdit): string {
  if (!draft.title.trim() || Array.from(draft.title).length > 50) return '标题需为 1～50 字'
  if (Array.from(draft.summary).length > 500) return '摘要最多 500 字'
  if (!draft.content.trim() || Array.from(draft.content).length > 100000) return '正文不能为空，且最多 100000 字'
  return ''
}
