export type WritingReferenceKind = 'draft' | 'article' | 'selection'
export interface WritingReference { kind: WritingReferenceKind; text: string; truncated: boolean }
export interface AttachedWritingReference extends WritingReference { id: string }
export interface SelectionReferenceRequest { id: string; text: string }

const START = '\n\n<easyjob-writing-reference>\n'
const END = '\n</easyjob-writing-reference>'
export const WRITING_REFERENCE_LIMIT = 12000
export const MAX_WRITING_REFERENCES = 5
export function referenceLabel(kind: WritingReferenceKind) { return kind === 'draft' ? '当前草稿' : kind === 'article' ? '当前文章' : '选中文字' }
export function validWritingReference(value: unknown): value is WritingReference {
  if (!value || typeof value !== 'object') return false
  const ref = value as WritingReference
  return (ref.kind === 'draft' || ref.kind === 'article' || ref.kind === 'selection') && typeof ref.text === 'string'
    && !!ref.text.trim() && ref.text.length <= WRITING_REFERENCE_LIMIT && typeof ref.truncated === 'boolean'
}

// References travel through the existing user-message/history contract. Keep the
// instruction separate in the UI and decode only a complete, bounded envelope.
export function writingReferencesError(references: readonly WritingReference[]): string {
  if (references.length > MAX_WRITING_REFERENCES) return '本次最多引用 5 处，请先移除不需要的引用'
  if (!references.every(validWritingReference)) return '引用内容无效，请重新选择'
  if (references.reduce((total, ref) => total + ref.text.length, 0) > WRITING_REFERENCE_LIMIT) return '引用总长度超过 12000 字，请缩短选区或移除部分引用'
  return ''
}
function referenceData(reference: WritingReference): WritingReference {
  return { kind: reference.kind, text: reference.text, truncated: reference.truncated }
}
export function writingMessage(content: string, reference: WritingReference | readonly WritingReference[] | null): string {
  const references: readonly WritingReference[] = reference ? Array.isArray(reference) ? reference : [reference as WritingReference] : []
  const error = writingReferencesError(references)
  if (error) throw new Error(error)
  // Preserve the original envelope for one quote and accept it in all histories.
  const payload = references.length === 1 ? { version: 1, ...referenceData(references[0]!) } : { version: 2, references: references.map(referenceData) }
  const message = references.length ? `${content}${START}${JSON.stringify(payload)}${END}` : content
  if (message.length > 16000) throw new Error('问题和引用内容合计过长，请精简问题或引用更短的文字')
  return message
}
export function readWritingMessage(message: string): { content: string; reference?: WritingReference; references?: WritingReference[] } {
  const start = message.lastIndexOf(START)
  if (start < 0 || !message.endsWith(END) || message.length > 16000) return { content: message }
  try {
    const ref = JSON.parse(message.slice(start + START.length, -END.length))
    if (ref.version === 1 && validWritingReference(ref)) return {
      content: message.slice(0, start), reference: referenceData(ref)
    }
    if (ref.version === 2 && Array.isArray(ref.references) && ref.references.length && !writingReferencesError(ref.references)) return {
      content: message.slice(0, start), references: ref.references.map(referenceData)
    }
  } catch { /* Ordinary messages that resemble an envelope remain untouched. */ }
  return { content: message }
}
export function writingQuestionPreview(question: string) { return question.split(START)[0] }

export function mentionAt(text: string, caret: number) {
  const match = /(?:^|\s)@([^\s@]*)$/u.exec(text.slice(0, caret))
  return match ? { start: caret - match[1]!.length - 1, end: caret, query: match[1]! } : null
}
