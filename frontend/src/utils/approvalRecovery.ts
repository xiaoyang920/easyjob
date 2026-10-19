export function approvalRecovery(run: Record<string, any>) {
  const saved = run.draftArticleId || run.result?.draft_article_id
  if (saved) return { status: 'complete' as const, interrupted: false, articleId: String(saved), notice: '草稿已保存，可以打开文章继续编辑。' }
  if (run.status === 'awaiting_approval' && run.result?.interrupted) {
    return { status: 'awaiting' as const, interrupted: true, payload: run.result.interrupted, notice: '已核对最新草稿，请确认当前预览后操作。' }
  }
  if (run.status === 'running') return { status: 'working' as const, interrupted: false, notice: '操作正在执行，正在同步结果，请勿重复提交。' }
  if (run.result?.delivery_status === 'incomplete') return { status: 'error' as const, interrupted: false, notice: '本次请求尚未完成，可以继续提问。' }
  if (run.status === 'succeeded') return { status: 'complete' as const, interrupted: false, notice: '该操作已完成。' }
  if (run.status === 'cancelled') return { status: 'cancelled' as const, interrupted: false, notice: '该审批已取消，草稿预览仍保留。' }
  return { status: 'error' as const, interrupted: false, notice: run.status === 'expired' ? '该审批已过期，草稿预览仍保留；可发起新的写作请求。' : '该审批已失效，草稿预览仍保留。' }
}
