import { marked } from 'marked'
import { safeHtml } from './safeHtml.ts'
import { draftBodyHtml, type SourceLink } from './citationLinks.ts'

export interface EditorSnapshot {
  document_id: string; snapshot_id: string; title: string; summary: string
  content: string; content_complete: boolean; selection: string; body_replaceable?: boolean
  content_format: 'html' | 'text'
}
export interface EditorProposal {
  id: string; documentId: string; snapshotId: string; target: 'title' | 'summary' | 'body' | 'selection'
  before: string; after: string; explanation: string; format: 'markdown' | 'text'
  citations?: SourceLink[]
}
export type EditOutcome = { ok: boolean; message: string }
export function editorSnapshotContent(html: string, text: string) {
  const useHtml = html.length <= 32000
  const content = useHtml ? html : text
  return { content: content.slice(0, 32000), content_format: useHtml ? 'html' as const : 'text' as const,
    content_complete: content.length <= 32000 && !/<(?:video|audio|iframe)\b/i.test(html), body_replaceable: useHtml }
}
export function parseEditorProposals(value: unknown): EditorProposal[] {
  if (!Array.isArray(value) || value.length > 1) return []
  return value.filter((p): p is EditorProposal => !!p && ['title', 'summary', 'body', 'selection'].includes(p.target)
    && ['id', 'documentId', 'snapshotId', 'before', 'after', 'explanation'].every(k => typeof p[k] === 'string')
    && /^[a-f0-9]{64}$/.test(p.id) && /^[a-f0-9-]{36}$/i.test(p.snapshotId) && /^[a-f0-9-]{36}$/i.test(p.documentId)
    && p.before.length <= 32000 && p.after.length > 0 && p.after.length <= 16000 && p.explanation.length <= 500
    && (p.target === 'body' ? p.format === 'markdown' : p.format === 'text')
    && (p.target !== 'title' || p.after.trim().length <= 100)
    && (p.target !== 'summary' || p.after.trim().length <= 500))
    .map(p => ({ ...p, citations: Array.isArray(p.citations) ? p.citations.filter(s => s && typeof s.id === 'string' && s.id.length <= 200).slice(0, 32).map(s => ({ id: s.id })) : [] }))
}
export function editorReplacementHtml(markdown: string, citations: SourceLink[] = []) {
  return draftBodyHtml(safeHtml(marked.parse(markdown, { breaks: true, gfm: true }) as string), citations)
}
