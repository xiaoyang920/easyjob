import { Boot, DomEditor, SlateEditor, SlateElement, SlateRange, SlateText, SlateTransforms, type IDomEditor } from '@wangeditor/editor'
import { articleTextStyle, blockIndentPixels, indentPixels, MAX_BLOCK_DEPTH, TAB_INDENT_PX } from './articleTextStyle'

export type OutlineBlock = SlateElement & { type: string; blockIndent?: number; indent?: string; textAlign?: string; lineHeight?: string; blockFontSize?: string }
// Two explicit Tabs in an empty block opt into destination-relative paste.
// Inheriting indentation through Enter/loading does not express that intent.
const pasteTargets = new WeakMap<IDomEditor, { path: ReturnType<typeof SlateEditor.pathRef>; node: OutlineBlock; baseDepth: number; prepared: boolean; depth: number; firstLine: number }>()
function pasteTargetAt(editor: IDomEditor, index: number) {
  const tracked = pasteTargets.get(editor)
  if (!tracked) return undefined
  // HTML paste removes its empty placeholder. Undo reinserts that same Slate
  // node: recover its intent without matching unrelated blocks by text/format.
  if (!tracked.path.current) {
    const restored = editor.children.indexOf(tracked.node)
    if (restored >= 0) tracked.path = SlateEditor.pathRef(editor,[restored],{affinity:'backward'})
  }
  if (tracked.path.current?.[0] !== index) return undefined
  const node = editor.children[index]
  // Undo can restore the prepared format before another action uses it. Once
  // an action observes an outdent, discard the anchor so it cannot revive
  // merely because later content happens to have the same indentation.
  if (isOutlineBlock(node) && blockDepth(node) === tracked.depth
    && (indentPixels(node.indent || '') || 0) === tracked.firstLine) return tracked
  tracked.path.unref()
  pasteTargets.delete(editor)
  return undefined
}
function rememberPasteBase(editor: IDomEditor, index: number, node: OutlineBlock, baseDepth: number, prepared: boolean) {
  pasteTargets.get(editor)?.path.unref()
  // Enter splits the current block. Its paste intent belongs to the original
  // block, not the newly created paragraph that follows it.
  pasteTargets.set(editor, {path:SlateEditor.pathRef(editor,[index],{affinity:'backward'}),node,baseDepth,prepared,
    depth:blockDepth(node),firstLine:indentPixels(node.indent || '') || 0})
}
export function outlinePasteDepth(editor: IDomEditor, path: number[]): number | undefined {
  const tracked = pasteTargetAt(editor,path[0]!)
  if (!tracked?.prepared) return undefined
  const node = editor.children[path[0]!]
  if (!isOutlineBlock(node) || !SlateEditor.isEmpty(editor, node) || !blockDepth(node)) return undefined
  tracked.node = node
  return tracked.baseDepth
}
export function isOutlineBlock(node: unknown): node is OutlineBlock {
  return SlateElement.isElement(node) && /^(paragraph|header[1-6]|blockquote)$/.test(DomEditor.getNodeType(node))
}
export function blockDepth(node: unknown): number {
  const depth = (node as { blockIndent?: unknown } | null)?.blockIndent
  return typeof depth === 'number' && Number.isInteger(depth) ? Math.max(0, Math.min(MAX_BLOCK_DEPTH, depth)) : 0
}
function setDepth(editor: IDomEditor, index: number, depth: number) {
  SlateTransforms.setNodes<OutlineBlock>(editor, { blockIndent: depth || undefined }, { at: [index] })
}
/** Format only the selected blocks; indentation does not require a preceding parent. */
export function indentOutline(editor: IDomEditor, backwards: boolean): { handled: boolean; limited: boolean } {
  const selection = editor.selection
  if (!selection || editor.isDisabled()) return { handled: false, limited: false }
  const [firstPoint, lastPoint] = SlateRange.edges(selection)
  const indices = [...SlateEditor.nodes(editor, { match: isOutlineBlock, mode: 'highest' })]
    .filter(([,path]) => path.length === 1 && !(firstPoint.path[0] !== lastPoint.path[0]
      && path[0] === lastPoint.path[0] && SlateEditor.isStart(editor, lastPoint, path)))
    .map(([,path]) => path[0]!)
  if (!indices.length) return { handled: false, limited: false }
  const pasteTarget = SlateRange.isCollapsed(selection) ? pasteTargetAt(editor,indices[0]!) : undefined
  // A caret's first Tab changes only first-line formatting. A range moves blocks.
  if (SlateRange.isCollapsed(selection)) {
    const index = indices[0]!, node = editor.children[index] as OutlineBlock
    const firstLine = indentPixels(node.indent || '') || 0
    if ((backwards && firstLine > 0) || (!backwards && node.type === 'paragraph' && !firstLine)) {
      SlateTransforms.setNodes<OutlineBlock>(editor, { indent: backwards
        ? firstLine > TAB_INDENT_PX ? `${firstLine - TAB_INDENT_PX}px` : undefined : `${TAB_INDENT_PX}px` }, { at: [index] })
      if (!backwards && SlateEditor.isEmpty(editor,node) && !(pasteTarget?.prepared && blockDepth(node))) {
        // Remember the text's first-Tab position, but don't rebase a paste yet.
        rememberPasteBase(editor,index,editor.children[index] as OutlineBlock,blockDepth(node)+1,false)
      }
      return { handled: true, limited: false }
    }
  }
  // A text selection formats only its selected blocks. Never expand it into
  // unselected descendants merely because they follow a shallower heading.
  const changes = new Map<number, number>()
  for (const index of indices) {
    const depth = blockDepth(editor.children[index]), next = Math.max(0, depth + (backwards ? -1 : 1))
    // These are independently authored offsets, including pasted fragments
    // whose parents were not copied. A preceding block must not cap Tab.
    if (!backwards && next > MAX_BLOCK_DEPTH) {
      return { handled: true, limited: true }
    }
    changes.set(index,next)
  }
  SlateEditor.withoutNormalizing(editor, () => { for (const [index,depth] of changes) setDepth(editor,index,depth) })
  if (!backwards && SlateRange.isCollapsed(selection)) {
    const index = indices[0]!, node = editor.children[index]
    if (isOutlineBlock(node) && SlateEditor.isEmpty(editor, node)) {
      // An Enter-inherited first-line indent is not an explicit first Tab.
      // Record the first keypress's visible position, then opt in on the next.
      const firstLine = (indentPixels(node.indent || '') || 0) / TAB_INDENT_PX
      rememberPasteBase(editor,index,node,pasteTarget?.baseDepth ?? blockDepth(node)+firstLine,!!pasteTarget)
    }
  }
  return { handled: true, limited: false }
}

let registered = false
export function registerEditorOutline() {
  if (registered) return
  registered = true
  Boot.registerModule({
    renderStyle(node, vnode) {
      if (!isOutlineBlock(node)) return vnode
      vnode.data ||= {}; vnode.data.style ||= {}
      vnode.data.style.marginLeft = `${blockDepth(node) * TAB_INDENT_PX}px`
      if (node.blockFontSize) vnode.data.style.fontSize = node.blockFontSize
      return vnode
    },
    styleToHtml(node, html) {
      if (!isOutlineBlock(node) || (!blockDepth(node) && !node.blockFontSize)) return html
      const template = document.createElement('template'); template.innerHTML = html
      const element = template.content.firstElementChild as HTMLElement | null
      if (element) {
        if (blockDepth(node)) element.style.marginLeft = `${blockDepth(node) * TAB_INDENT_PX}px`
        if (node.blockFontSize) element.style.fontSize = node.blockFontSize
      }
      return template.innerHTML
    },
    parseStyleHtml(element, node) {
      const style = articleTextStyle(isOutlineBlock(node) ? 'p' : 'span', (element as HTMLElement).getAttribute('style') || '')
      const fontSize = style.match(/(?:^|;)\s*font-size: ([^;]+);/)?.[1]
      // The native importer only accepts sizes/heights in its toolbar dropdown.
      // Imported document formatting may use other values in our safe range.
      if (SlateText.isText(node) && fontSize && !(node as {fontSize?:string}).fontSize) (node as {fontSize?:string}).fontSize = fontSize
      if (isOutlineBlock(node)) {
        if (fontSize) node.blockFontSize = fontSize
        const lineHeight = style.match(/(?:^|;)\s*line-height: ([^;]+);/)?.[1]
        if (lineHeight) node.lineHeight = lineHeight
        const pixels = blockIndentPixels((element as HTMLElement).style.marginLeft)
        if (pixels) node.blockIndent = pixels / TAB_INDENT_PX
      }
      return node
    },
    editorPlugin(editor) {
      editor.on('destroyed', () => { pasteTargets.get(editor)?.path.unref(); pasteTargets.delete(editor) })
      const removeMark = editor.removeMark
      editor.removeMark = key => {
        // Restoring a whole imported heading's default size must clear its
        // block size as well as its text marks. Partial selections stay local.
        const range = editor.selection
        const blocks = key === 'fontSize' && range ? [...SlateEditor.nodes(editor,{match:isOutlineBlock})]
          .filter(([,path]) => path.length === 1 && SlateRange.includes(range,SlateEditor.start(editor,path))
            && SlateRange.includes(range,SlateEditor.end(editor,path))) : []
        SlateEditor.withoutNormalizing(editor, () => {
          removeMark(key)
          for (const [,path] of blocks) SlateTransforms.unsetNodes(editor,'blockFontSize',{at:path})
        })
      }
      const normalize = editor.normalizeNode
      editor.normalizeNode = entry => {
        if (!entry[1].length) {
          for (let index = 0; index < editor.children.length; index++) {
            const node = editor.children[index]
            // A copied subtree may start at an absolute authored offset without
            // its original parent. Keep that offset on paste, reload and undo.
            const depth = blockDepth(node)
            if (isOutlineBlock(node) && node.blockIndent !== undefined && node.blockIndent !== depth) {
              setDepth(editor, index, depth); return
            }
          }
        }
        normalize(entry)
      }
      return editor
    },
  })
}
