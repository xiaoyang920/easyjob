// Use the server's latest status; missing or moderated states must not become drafts.
export function editableArticleStatus(status: unknown): 0 | 1 {
  if (status === 0 || status === 1) return status
  throw new Error('文章状态已变化或无法编辑，请刷新后重试')
}

export function savedArticlePath(articleId: string, status: unknown): string {
  return editableArticleStatus(status) === 1
    ? `/article/${encodeURIComponent(articleId)}`
    : `/edit-article?id=${encodeURIComponent(articleId)}`
}
