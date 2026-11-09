import { Boot, SlateEditor, SlateRange, type IDomEditor, type IButtonMenu } from '@wangeditor/editor'

export const editorReferenceMenuKey = 'articleAiReference'
type ReferenceHandler = (text: string, range: SlateRange) => void
const handlers = new WeakMap<IDomEditor, { selection: () => SlateRange | null; quote: ReferenceHandler }>()
let registered = false

class EditorReferenceMenu implements IButtonMenu {
  readonly title = '引用给 AI'
  readonly tag = 'button'
  getValue(): string { return '' }
  isActive(): boolean { return false }
  isDisabled(editor: IDomEditor): boolean {
    const range = handlers.get(editor)?.selection()
    if (editor.isDisabled() || !range || SlateRange.isCollapsed(range)) return true
    try { return !SlateEditor.string(editor, range).trim() } catch { return true }
  }
  exec(editor: IDomEditor): void {
    if (this.isDisabled(editor)) return
    const binding = handlers.get(editor)!
    const range = structuredClone(binding.selection()!)
    binding.quote(SlateEditor.string(editor, range), range)
  }
}

export function registerEditorReferenceMenu() {
  if (registered) return
  Boot.registerMenu({ key: editorReferenceMenuKey, factory: () => new EditorReferenceMenu() })
  registered = true
}
export function bindEditorReference(editor: IDomEditor, selection: () => SlateRange | null, handler: ReferenceHandler): () => void {
  handlers.set(editor, { selection, quote: handler })
  return () => { handlers.delete(editor) }
}
