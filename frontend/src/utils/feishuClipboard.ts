import { articleTextStyle, MAX_BLOCK_DEPTH, TAB_INDENT_PX } from './articleTextStyle.ts'
import { safeHtml } from './safeHtml.ts'

type Snapshot = { type?: string; parent_id?: string; text_indent?: number; align?: string }
type RecordData = { rootId?: string; recordMap?: Record<string, { snapshot?: Snapshot }> }
const MAX_RECORD_SIZE = 2_000_000
const structural = 'table,pre,ul,ol,hr,blockquote'
const line = '.ace-line,[class*="old-record-id-"]'

function readRecord(value: string): RecordData | null {
  if (!value || value.length > MAX_RECORD_SIZE) return null
  try { const record = JSON.parse(value); return record && typeof record === 'object' ? record : null } catch { return null }
}
function recordId(node: Element): string | undefined {
  return [...node.classList].find(name => name.startsWith('old-record-id-'))?.slice('old-record-id-'.length)
}

/** Convert Feishu's portable clipboard HTML and public clipboard metadata only.
 * No account/API access, record text decoding, or remote resource fetching. */
export function feishuClipboardHtml(data: Pick<DataTransfer, 'getData'>): string | null {
  const html = data.getData('text/html')
  if (!html || !/data-lark-html-role|data-lark-record-data|old-record-id-/.test(html)) return null
  const source = document.createElement('div'); source.innerHTML = html
  // Our outbound HTML already contains its original semantic blocks/styles.
  // The appended Feishu payload must not route a return paste through Feishu's HTML importer.
  if (source.querySelector('[data-ej-feishu-copy="1"]')) return null
  const metadata = source.querySelector('[data-lark-record-data]')
  const record = readRecord(data.getData('docx/record'))
    ?? readRecord(metadata?.getAttribute('data-lark-record-data') || '')
  source.querySelectorAll('.lark-record-clipboard,[data-lark-record-data],meta,script,style').forEach(node => node.remove())
  const root = source.querySelector('[data-lark-html-role="root"]') || source
  const output = document.createElement('div')
  const snapshot = (id?: string): Snapshot | undefined => {
    const value = id ? record?.recordMap?.[id]?.snapshot : undefined
    if (!value || typeof value !== 'object') return undefined
    return {
      type:typeof value.type === 'string' ? value.type : undefined,
      parent_id:typeof value.parent_id === 'string' ? value.parent_id : undefined,
      text_indent:value.text_indent === 0 || value.text_indent === 1 ? value.text_indent : undefined,
      align:typeof value.align === 'string' ? value.align : undefined,
    }
  }
  const absoluteDepth = (id: string | undefined, fallback: number): number => {
    let parent = snapshot(id)?.parent_id, depth = 0
    if (parent === undefined) return fallback
    const visited = new Set<string>(id ? [id] : [])
    while (parent && parent !== record?.rootId && snapshot(parent)?.type !== 'page') {
      if (visited.has(parent)) return fallback
      visited.add(parent); depth++
      if (depth >= MAX_BLOCK_DEPTH) return MAX_BLOCK_DEPTH
      const next: string | undefined = snapshot(parent)?.parent_id
      if (next === undefined) return Math.max(depth, fallback)
      parent = next
    }
    return depth
  }
  type Marks = Partial<Record<'strong'|'em'|'u'|'s'|'code'|'sup'|'sub',boolean>>
  // Emit portable runs with one outer style span and semantic marks inside it.
  // Native HTML import drops styles buried inside nested strong/em wrappers.
  function inline(node: Node, into: Node, nested: HTMLElement[], inheritedStyle: string,
      marks: Marks = {}, link?: { href: string; title: string }) {
    if (node.nodeType === 3) {
      const span = document.createElement('span')
      const style = articleTextStyle('span',inheritedStyle)
      if (style) span.setAttribute('style',style)
      let contents: HTMLElement = span
      for (const tag of ['strong','em','u','s','code','sup','sub'] as const) if (marks[tag]) {
        const mark = document.createElement(tag); contents.append(mark); contents = mark
      }
      contents.append(node.cloneNode())
      if (link) {
        const anchor = document.createElement('a'); anchor.setAttribute('href',link.href)
        if (link.title) anchor.title = link.title
        anchor.append(span); into.appendChild(anchor)
      } else into.appendChild(span)
      return
    }
    if (!(node instanceof HTMLElement)) return
    if (node.matches(`${line},${structural}`)) { nested.push(node); return }
    if (node.matches('img,br')) {
      const element = document.createElement(node.tagName.toLowerCase())
      for (const name of ['src','alt','title']) {
        const value = node.getAttribute(name); if (value !== null) element.setAttribute(name,value)
      }
      into.appendChild(element); return
    }
    const style = articleTextStyle('span',`${inheritedStyle};${node.getAttribute('style') || ''}`)
    const next = { ...marks }
    if (node.matches('b,strong') || /^(bold|[6-9]00)$/.test(node.style.fontWeight)) next.strong = true
    if (node.matches('i,em') || node.style.fontStyle === 'italic') next.em = true
    if (node.matches('u') || /underline/.test(node.style.textDecoration + node.style.textDecorationLine)) next.u = true
    if (node.matches('s,del,strike') || /line-through/.test(node.style.textDecoration + node.style.textDecorationLine)) next.s = true
    if (node.matches('code')) next.code = true
    if (node.matches('sup')) next.sup = true
    if (node.matches('sub')) next.sub = true
    if (node.matches('a')) link = {href:node.getAttribute('href') || '',title:node.getAttribute('title') || ''}
    for (const child of node.childNodes) inline(child,into,nested,style,next,link)
  }
  function visit(node: Node, inherited = '', nestedDepth = 0) {
    if (!(node instanceof HTMLElement)) {
      if (node.textContent?.trim()) { const paragraph = document.createElement('p'); paragraph.textContent = node.textContent; output.append(paragraph) }
      return
    }
    if (node.matches(structural)) {
      // Preserve native lists, tables and code as units; don't turn cell/list
      // paragraphs into unrelated outline blocks.
      const clone = node.cloneNode(true) as HTMLElement
      for (const element of [clone,...clone.querySelectorAll<HTMLElement>('*')]) {
        const language = [...element.classList].find(name => /^language-[\w-]+$/.test(name))
        element.removeAttribute('class'); element.removeAttribute('id')
        if (language && element.tagName === 'CODE') element.className = language
      }
      output.append(clone); return
    }
    const inheritedStyle = `${inherited};${node.getAttribute('style') || ''}`
    if (!node.matches(line)) {
      for (const child of node.childNodes) visit(child,inheritedStyle,nestedDepth)
      return
    }
    const blockRecord = snapshot(recordId(node))
    const heading = blockRecord?.type?.match(/^heading([1-6])$/)?.[1] || node.tagName.match(/^H([1-6])$/)?.[1]
    const tag = heading ? `h${heading}` : 'p'
    const block = document.createElement(tag), children: HTMLElement[] = []
    // Preserve authored sizes only. A semantic heading without a size uses the
    // site's heading typography, instead of persisting a guessed Feishu size.
    for (const child of node.childNodes) inline(child,block,children,inheritedStyle)
    const walker = document.createTreeWalker(block,NodeFilter.SHOW_TEXT), firstText = walker.nextNode()
    const prefix = firstText?.textContent?.match(/^\u00a0+/)?.[0].length || 0
    const depth = Math.min(MAX_BLOCK_DEPTH, absoluteDepth(recordId(node), Math.max(nestedDepth,Math.floor(prefix/2))))
    // Feishu emits two NBSPs per structural level, in addition to its metadata.
    // Remove only that generated prefix, preserving any further authored spaces.
    if (firstText && prefix >= depth*2 && depth) firstText.textContent = firstText.textContent!.slice(depth*2)
    let style = articleTextStyle(tag,inheritedStyle).split(';')
      .filter(value => !/^\s*(text-indent|margin-left):/.test(value)).join(';')
      + ';' + articleTextStyle(tag,node.getAttribute('style') || '')
    if (depth) style += ` margin-left: ${depth*TAB_INDENT_PX}px;`
    if (blockRecord?.text_indent === 1) style += ` text-indent: ${TAB_INDENT_PX}px;`
    if (blockRecord?.text_indent === 0) style += ' text-indent: 0px;'
    if (blockRecord?.align) style += articleTextStyle(tag,`text-align:${blockRecord.align}`)
    if (!/line-height:/.test(style)) style += ` line-height: ${heading ? '1.4' : '1.625'};`
    if (style) block.setAttribute('style',articleTextStyle(tag,style))
    if (block.textContent || block.querySelector('img,br') || !children.length) output.append(block)
    for (const child of children) visit(child,inherited,depth+1)
  }
  for (const child of root.childNodes) visit(child,root.getAttribute('style') || '')
  return output.childNodes.length ? safeHtml(output.innerHTML) : null
}
