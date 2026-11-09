import { editorSnapshotContent, type EditorSnapshot, type EditorProposal, type EditOutcome } from './editorTools.ts'

interface EditorRead {
  html: string
  text: string
  selection: string
}

interface EditorBridge<Read extends EditorRead> {
  readDocument: () => Read
  captureSnapshot: (id: string, source: Read) => void
  releaseSnapshot: (id: string) => void
  clearSnapshots: () => void
  applyProposal: (proposal: EditorProposal, snapshotId: string) => EditOutcome
  undoProposal: (id: string) => EditOutcome
}

export function createEditorProposalController<Read extends EditorRead>(options: {
  getEditor: () => EditorBridge<Read> | undefined
  getFields: () => { title: string; summary: string }
  canEdit: () => boolean
  onSummaryApplied: () => void
}) {
  const documentId = crypto.randomUUID()
  const snapshots = new Map<string, EditorSnapshot>()
  const applied = new Set<string>()
  const undoRecords = new Map<string, { before: string; after: string; target: EditorProposal['target'] }>()

  function read(): EditorSnapshot | null {
    const editor = options.getEditor()
    if (!options.canEdit() || !editor) return null
    const source = editor.readDocument()
    const fields = options.getFields()
    const snapshot: EditorSnapshot = { document_id: documentId, snapshot_id: crypto.randomUUID(),
      title: fields.title, summary: fields.summary, ...editorSnapshotContent(source.html, source.text),
      selection: source.selection.length <= 12000 ? source.selection : '' }
    editor.captureSnapshot(snapshot.snapshot_id, source)
    snapshots.set(snapshot.snapshot_id, snapshot)
    if (snapshots.size > 8) {
      const expired = snapshots.keys().next().value!
      editor.releaseSnapshot(expired)
      snapshots.delete(expired)
    }
    return snapshot
  }

  function apply(proposal: EditorProposal): EditOutcome {
    const snapshot = snapshots.get(proposal.snapshotId)
    if (!snapshot || proposal.documentId !== documentId) return { ok: false, message: '这条建议对应的编辑快照已失效，请重新生成' }
    if (applied.has(proposal.id)) return { ok: false, message: '这条建议已经应用过了' }
    const editor = options.getEditor()
    if (!options.canEdit() || !editor) return { ok: false, message: '当前版本不可编辑' }
    const fields = options.getFields()
    const field = proposal.target === 'title' || proposal.target === 'summary' ? proposal.target : null
    const label = field === 'title' ? '标题' : '摘要'
    if (field && snapshot[field] !== fields[field]) return { ok: false, message: `${label}已在生成建议后发生变化，请重新生成` }
    const expected = field ? snapshot[field] : proposal.target === 'body' ? snapshot.content : snapshot.selection
    if (expected !== proposal.before || !proposal.after.trim()
        || (proposal.target === 'body' && (!snapshot.content_complete || snapshot.body_replaceable === false))) {
      return { ok: false, message: '修改建议与原文不匹配，请重新生成' }
    }
    const result = field ? (fields[field] = proposal.after.trim(), { ok: true, message: `${label}已更新` }) : editor.applyProposal(proposal, proposal.snapshotId)
    if (result.ok) {
      if (field === 'summary') options.onSummaryApplied()
      applied.add(proposal.id)
      if (applied.size > 8) applied.delete(applied.values().next().value!)
      undoRecords.set(proposal.id, { before: expected, after: field ? fields[field] : proposal.after, target: proposal.target })
      if (undoRecords.size > 8) undoRecords.delete(undoRecords.keys().next().value!)
      editor.releaseSnapshot(proposal.snapshotId)
      snapshots.delete(proposal.snapshotId)
    }
    return result
  }

  function undo(proposal: EditorProposal): EditOutcome {
    const record = undoRecords.get(proposal.id)
    const editor = options.getEditor()
    if (!record || !editor || !options.canEdit()) return { ok: false, message: '这条修改已不能撤销' }
    const fields = options.getFields()
    const field = record.target === 'title' || record.target === 'summary' ? record.target : null
    const label = field === 'title' ? '标题' : '摘要'
    if (field && fields[field] !== record.after) return { ok: false, message: `${label}已继续修改，未覆盖你的新内容` }
    const result = field ? (fields[field] = record.before, { ok: true, message: `已恢复原来的${label}` }) : editor.undoProposal(proposal.id)
    if (result.ok) undoRecords.delete(proposal.id)
    return result
  }

  function reset() {
    options.getEditor()?.clearSnapshots()
    snapshots.clear()
    applied.clear()
    undoRecords.clear()
  }

  return { read, apply, undo, reset }
}
