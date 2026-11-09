import type { SlateNode } from '@wangeditor/editor'
import { indentPixels, MAX_BLOCK_DEPTH } from './articleTextStyle.ts'

type CopyNode = { type?: string; text?: string; children?: CopyNode[]; blockIndent?: number; indent?: string; textAlign?: string; url?: string; bold?: boolean; italic?: boolean; underline?: boolean; through?: boolean; code?: boolean }
type Attribute = [string, string]
type RichText = { initialAttributedTexts: { text: Record<string, string>; attribs: Record<string, string> }; apool: { numToAttrib: Record<string, Attribute>; nextNum: number; attribToNum: Record<string, number> } }
type Snapshot = { type: string; parent_id: string; children: string[]; text?: RichText; text_indent?: number; align?: string; folded?: boolean; comments?: never[]; revisions?: never[] }

/** Clipboard-only adapter, verified against Feishu's normal copy/paste format.
 * Keep the original HTML/Slate fragment; no source IDs, authors or app state leave the editor. */
export function feishuClipboardRecord(fragment: readonly SlateNode[], startsInsideBlock = false): string | null {
  if (!fragment.length) return null
  const prefix = `ej-copy-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  const rootId = `${prefix}-root`, roots: string[] = [], parents: string[] = []
  const recordMap: Record<string, { id: string; snapshot: Snapshot }> = {
    [rootId]: { id: rootId, snapshot: { type: 'page', parent_id: '', children: roots } },
  }
  const selected: { id: number; type: string; recordId: string }[] = []
  for (const [index, value] of fragment.entries()) {
    const node = value as CopyNode
    // Unsupported structural/media blocks keep the complete standard HTML path.
    // Never supply a partial record that would make Feishu drop those blocks.
    if (!node.type || !/^(paragraph|header[1-6])$/.test(node.type) || !node.children) return null
    const depth = node.blockIndent ?? 0, firstLine = indentPixels(node.indent || '0px')
    if (!Number.isInteger(depth) || depth < 0 || depth > MAX_BLOCK_DEPTH || firstLine === null) return null
    const inlineOnly = startsInsideBlock && fragment.length === 1
    const effectiveDepth = inlineOnly ? 0 : depth
    // A copied subtree does not carry unselected ancestors. Attach it at the
    // destination root, retaining the relationships expressible inside the selection.
    let parentDepth = effectiveDepth - 1
    while (parentDepth >= 0 && !parents[parentDepth]) parentDepth--
    const parent = parentDepth >= 0 ? parents[parentDepth]! : rootId
    const text = richText(node.children)
    if (!text) return null
    const id = `${prefix}-${index}`, type = node.type === 'paragraph' || inlineOnly ? 'text' : node.type.replace('header', 'heading')
    recordMap[id] = { id, snapshot: {
      // Feishu exposes a two-character first-line option rather than an arbitrary pixel distance.
      type, parent_id: parent, children: [], text, text_indent: !inlineOnly && firstLine > 0 ? 1 : 0,
      ...(node.textAlign && /^(left|center|right|justify)$/.test(node.textAlign) ? { align: node.textAlign } : {}),
      folded: false, comments: [], revisions: [],
    } }
    recordMap[parent]!.snapshot.children.push(id)
    parents[effectiveDepth] = id; parents.length = effectiveDepth + 1
    if (parent === rootId) selected.push({ id: index + 1, type, recordId: id })
  }
  const record = JSON.stringify({
    isCut: false, rootId, parentId: rootId, blockIds: selected.map(item => item.id), recordIds: roots,
    recordMap, payloadMap: {}, extra: { channel: 'saas', isEqualBlockSelection: true },
    isKeepQuoteContainer: false, selection: selected,
  })
  return record.length <= 2_000_000 ? record : null
}

function richText(children: CopyNode[]): RichText | null {
  const pool: Attribute[] = [], indexes = new Map<string, number>()
  let text = '', attribs = '', supported = true
  function append(value: string, attributes: Attribute[]) {
    const prefix = attributes.map(attribute => {
      const key = JSON.stringify(attribute)
      if (!indexes.has(key)) { indexes.set(key, pool.length); pool.push(attribute) }
      return `*${indexes.get(key)!.toString(36)}`
    }).join('')
    text += value
    const lastBreak = value.lastIndexOf('\n')
    if (lastBreak >= 0) {
      const line = value.slice(0, lastBreak + 1), rest = value.slice(lastBreak + 1), lines = line.split('\n').length - 1
      attribs += `${prefix}|${lines.toString(36)}+${line.length.toString(36)}`
      if (rest) attribs += `${prefix}+${rest.length.toString(36)}`
    } else if (value) attribs += `${prefix}+${value.length.toString(36)}`
  }
  function visit(node: CopyNode, inherited: Attribute[]) {
    if (typeof node.text === 'string') {
      const attributes = [...inherited]
      for (const [mark, name] of [['bold', 'bold'], ['italic', 'italic'], ['underline', 'underline'], ['through', 'strikethrough'], ['code', 'inlineCode']] as const) {
        if (node[mark]) attributes.push([name, 'true'])
      }
      append(node.text, attributes)
    } else if (node.type === 'link' && node.children && node.url && /^(https?:|mailto:)/i.test(node.url)) {
      for (const child of node.children) visit(child, [...inherited, ['link', encodeURIComponent(node.url)]])
    } else supported = false
  }
  for (const node of children) visit(node, [])
  return supported ? { initialAttributedTexts: { text: { '0': text }, attribs: { '0': attribs } }, apool: {
    numToAttrib: Object.fromEntries(pool.map((attribute, index) => [index, attribute])), nextNum: pool.length,
    attribToNum: Object.fromEntries(pool.map(([name, value], index) => [`${name},${value}`, index])),
  } } : null
}

export function appendFeishuClipboardRecord(contents: HTMLElement, record: string): void {
  const metadata = document.createElement('span')
  metadata.className = 'lark-record-clipboard'
  metadata.hidden = true
  metadata.setAttribute('data-ej-feishu-copy', '1')
  metadata.setAttribute('data-lark-record-format', 'docx/record')
  metadata.setAttribute('data-lark-record-data', record)
  contents.append(metadata)
}
