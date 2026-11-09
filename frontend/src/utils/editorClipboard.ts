import { DomEditor, SlateEditor, SlateElement, SlateNode, SlateRange, SlateTransforms, type IDomEditor } from '@wangeditor/editor'
import { articleTextStyle, blockIndentPixels, indentPixels, MAX_BLOCK_DEPTH, MAX_INDENT_PX, TAB_INDENT_PX } from './articleTextStyle'
import { blockDepth, isOutlineBlock, outlinePasteDepth, type OutlineBlock } from './editorOutline'
import { feishuClipboardHtml } from './feishuClipboard'
import { appendFeishuClipboardRecord, feishuClipboardRecord } from './feishuClipboardExport'

const textBlock = (node: SlateNode) => SlateElement.isElement(node) && /^(paragraph|header[1-6]|blockquote)$/.test(DomEditor.getNodeType(node))

/** Keep native rich fragments/marks/images, adding the paragraph wrapper that
 * cloneContents omits for a selection contained in one paragraph. */
export function installEditorClipboard(editor: IDomEditor): void {
  const copy = editor.setFragmentData.bind(editor), paste = editor.insertData.bind(editor)
  editor.setFragmentData = data => {
    copy(data)
    const selection = editor.selection
    if (!selection || SlateRange.isCollapsed(selection)) return
    const [start, end] = SlateRange.edges(selection)
    const fragment = editor.getFragment()
    const feishuRecord = feishuClipboardRecord(fragment, !SlateEditor.isStart(editor, start, [start.path[0]!]))
    const html = data.getData('text/html')
    if (html) {
      const contents = document.createElement('div')
      if (start.path[0] === end.path[0] && fragment.length === 1 && textBlock(fragment[0]!)) {
        const source = SlateEditor.node(editor, [start.path[0]!])[0]
        const wrapper = DomEditor.toDOMNode(editor, source).cloneNode(false) as HTMLElement
        wrapper.innerHTML = html
        contents.append(wrapper)
      } else contents.innerHTML = html
      // Editor-only wrapper spans hide the authored styles from HTML importers.
      // Keep styled spans, but unwrap structural spans in the clipboard clone.
      for (const element of contents.querySelectorAll<HTMLElement>('span[data-slate-node="text"],span[data-slate-leaf],span[data-slate-string],span[data-slate-zero-width]')) {
        if (!element.getAttribute('style')) element.replaceWith(...element.childNodes)
      }
      // Rendering puts font/color on strong/em/etc. Use portable styled spans;
      // normalize the clipboard only, never the source or its undo history.
      for (const element of contents.querySelectorAll<HTMLElement>('strong[style],b[style],em[style],i[style],u[style],s[style],del[style],a[style],code[style]')) {
        if (element.closest('pre')) continue
        const style = articleTextStyle('span', element.getAttribute('style') || '')
        if (!style) continue
        const span = document.createElement('span')
        span.setAttribute('style', style)
        element.before(span); span.append(element)
        element.removeAttribute('style')
      }
      for (const element of contents.querySelectorAll('[id]')) element.removeAttribute('id')
      const encoded = data.getData('application/x-slate-fragment')
      if (encoded) contents.firstElementChild?.setAttribute('data-slate-fragment', encoded)
      if (feishuRecord) appendFeishuClipboardRecord(contents, feishuRecord)
      data.setData('text/html', contents.innerHTML)
    }
    if (feishuRecord) {
      try { data.setData('docx/record', feishuRecord) } catch { /* HTML carries the same record when custom MIME is unavailable. */ }
    }
    // A CSS indent has no text representation. Tabs keep it when copying into
    // plain-text editors; a mid-paragraph selection does not gain a prefix.
    if (fragment.length && fragment.every(textBlock)) {
      data.setData('text/plain', fragment.map((node, index) => {
        const pixels = indentPixels((node as { indent?: string }).indent || '') || 0
        const prefix = index > 0 || SlateEditor.isStart(editor, start, [start.path[0]!])
          ? '\t'.repeat(blockDepth(node) + Math.floor(pixels / TAB_INDENT_PX)) + ' '.repeat((pixels % TAB_INDENT_PX) / 8) : ''
        return prefix + SlateNode.string(node)
      }).join('\n'))
    }
  }
  editor.insertData = data => {
    const selection = editor.selection
    if (editor.isDisabled()) return
    if (!selection) { paste(data); return }
    const path = [SlateRange.start(selection).path[0]!], target = SlateEditor.node(editor, path)[0]
    // Lists, code and table cells keep their own native paste semantics.
    if (!isOutlineBlock(target) || selection.anchor.path.length < 2) { paste(data); return }
    const preparedDepth = outlinePasteDepth(editor, path), overrides = new Map<string,string>()
    const encoded = data.getData('application/x-slate-fragment')
    let source: OutlineBlock | undefined
    const rebase = (depth: number, firstLine: number, base: number) => {
      if (preparedDepth === undefined) return {depth,firstLine}
      // The anchor is a visible text position, not just a block's margin.
      // Counting an existing first-line indent twice adds an unwanted Tab.
      const offset = preparedDepth * TAB_INDENT_PX + depth * TAB_INDENT_PX - base
      const nextDepth = Math.max(0,Math.min(MAX_BLOCK_DEPTH,Math.floor(offset / TAB_INDENT_PX)))
      return {
        depth:nextDepth,
        // If moving left would require a negative margin, consume first-line
        // indent instead. Half-stop legacy indents remain representable too.
        firstLine:Math.max(0,Math.min(MAX_INDENT_PX,firstLine + offset - nextDepth * TAB_INDENT_PX)),
      }
    }
    if (encoded) {
      try {
        const fragment: SlateNode[] = JSON.parse(decodeURIComponent(atob(encoded)))
        if (!Array.isArray(fragment) || !fragment.length) { paste(data); return }
        const blocks = fragment.filter(isOutlineBlock)
        const base = blocks.length ? Math.min(...blocks.map(node => blockDepth(node) * TAB_INDENT_PX + (indentPixels(node.indent || '') || 0))) : 0
        const rebased = fragment.map(node => {
          if (!isOutlineBlock(node)) return node
          const next = rebase(blockDepth(node),indentPixels(node.indent || '') || 0,base)
          return {...node,blockIndent:next.depth || undefined,
            ...(preparedDepth === undefined ? {} : {indent:next.firstLine ? `${next.firstLine}px` : undefined})}
        })
        if (isOutlineBlock(rebased[0])) source = rebased[0]
        overrides.set('application/x-slate-fragment', btoa(encodeURIComponent(JSON.stringify(rebased))))
      } catch { paste(data); return }
    } else {
      const html = feishuClipboardHtml(data) ?? data.getData('text/html')
      if (!html) { paste(data); return }
      const contents = document.createElement('div'); contents.innerHTML = html
      const selector = 'p,h1,h2,h3,h4,h5,h6,blockquote'
      const blocks = [...contents.querySelectorAll<HTMLElement>(selector)]
        .filter(node => !node.parentElement?.closest(`${selector},pre,li,td,th`))
      if (!blocks.length) { paste(data); return }
      const levels = blocks.map(node => (blockIndentPixels(node.style.marginLeft) || 0) / TAB_INDENT_PX)
      const firstLines = blocks.map(node => indentPixels(node.style.textIndent) || 0)
      const base = Math.min(...levels.map((depth,index) => depth * TAB_INDENT_PX + firstLines[index]!))
      blocks.forEach((node,index) => {
        const next = rebase(levels[index]!,firstLines[index]!,base)
        if (next.depth) node.style.marginLeft = `${next.depth * TAB_INDENT_PX}px`
        else node.style.removeProperty('margin-left')
        if (preparedDepth !== undefined) {
          if (next.firstLine) node.style.textIndent = `${next.firstLine}px`
          else node.style.removeProperty('text-indent')
        }
      })
      overrides.set('text/html', contents.innerHTML)
    }
    // Preserve files and native clipboard methods while changing only rich data.
    const incoming = new Proxy(data, { get(object, key) {
      if (key === 'getData') return (type: string) => overrides.get(type) ?? object.getData(type)
      const value = Reflect.get(object, key, object)
      return typeof value === 'function' ? value.bind(object) : value
    } })
    // Slate merges the first rich block into an empty target. Its first-line
    // formatting comes from the source, with explicit Tab paste using its
    // adjusted first-line position as well as its block offset.
    const tracked = source && SlateRange.isCollapsed(selection) && SlateEditor.isEmpty(editor, target)
      ? SlateEditor.pathRef(editor, path) : null
    type Operation = Parameters<IDomEditor['apply']>[0]
    const history = (editor as IDomEditor & {history:{undos:Operation[][];redos:Operation[][]}}).history
    const priorUndos = history.undos.map(batch=>[...batch]), operations: Operation[] = []
    const apply = editor.apply, before = structuredClone(selection)
    let completed = false
    editor.apply = operation => { operations.push(operation); apply(operation) }
    try {
      SlateEditor.withoutNormalizing(editor, () => {
        paste(incoming)
        if (!tracked?.current || !source) return
        SlateTransforms.setNodes(editor, { type: source.type, indent: source.indent, blockIndent: source.blockIndent,
          textAlign: source.textAlign, lineHeight: source.lineHeight, blockFontSize: source.blockFontSize } as Partial<SlateElement>, { at: tracked.current })
      })
      completed = true
    } finally {
      editor.apply = apply
      tracked?.unref()
      if (completed && operations.some(operation=>operation.type !== 'set_selection')) {
        // Pin both ends of this one paste transaction. The bundled Slate history
        // otherwise restores the caret to a preceding block after fragment undo.
        const pin = (range: SlateRange): Operation => ({type:'set_selection',properties:range,newProperties:range})
        const after = editor.selection && structuredClone(editor.selection)
        history.undos = [...priorUndos,[pin(before),...operations,...(after ? [pin(after)] : [])]].slice(-100)
        history.redos = []
      }
    }
  }
}
