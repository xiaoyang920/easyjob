/** Text quote selectors shared with ArticleCommentAnchorService (UTF-16 offsets). */
export interface CommentQuote { exact: string; prefix: string; suffix: string; start: number; end: number; contentHash?: string }
type Point = { node: Text; offset: number }
const blocks = new Set(['P','DIV','SECTION','ARTICLE','H1','H2','H3','H4','H5','H6','LI','UL','OL','PRE','BLOCKQUOTE','TABLE','TR','TD','TH','HR','BR','FIGURE','FIGCAPTION'])
const skip = new Set(['SCRIPT','STYLE','BUTTON','SVG','NOSCRIPT','TEMPLATE'])
const whitespace = /[\t\n\v\f\r \u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]/

export function articleTextIndex(root: Node) {
  const chars: string[] = [], starts: Point[] = [], ends: Point[] = []
  let space = false, spaceStart: Point | undefined
  function boundary(point?: Point) { space = true; spaceStart ||= point || ends.at(-1) }
  function walk(node: Node) {
    if (node.nodeType === 3) {
      const text = node as Text
      for (let i = 0; i < text.data.length; i++) {
        if (whitespace.test(text.data[i]!)) { boundary({ node: text, offset: i }); continue }
        const point = { node: text, offset: i }
        if (space && chars.length) { chars.push(' '); starts.push(spaceStart || point); ends.push(point) }
        space = false; spaceStart = undefined
        chars.push(text.data[i]!); starts.push(point); ends.push({ node: text, offset: i + 1 })
      }
      return
    }
    const element = node.nodeType === 1 ? node as Element : undefined
    if (element && (skip.has(element.tagName) || element.hasAttribute('data-annotation-ignore') || element.classList.contains('article-code-toolbar'))) return
    const block = !!element && blocks.has(element.tagName)
    if (block) boundary()
    node.childNodes.forEach(walk)
    if (block) boundary()
  }
  walk(root)
  return { text: chars.join(''), starts, ends }
}

function contextSlice(text: string, start: number, end: number) {
  // Avoid splitting a surrogate pair at the context window boundary.
  if (start > 0 && /[\uDC00-\uDFFF]/.test(text[start] || '')) start++
  if (/[\uD800-\uDBFF]/.test(text[end - 1] || '')) end--
  return text.slice(start, end)
}

export function selectedQuote(root: HTMLElement, selection: Selection | null): CommentQuote | undefined {
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return
  const range = selection.getRangeAt(0)
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return
  const exact = articleTextIndex(range.cloneContents()).text
  if (!exact || exact.length > 1000) return
  const before = range.cloneRange()
  before.selectNodeContents(root); before.setEnd(range.startContainer, range.startOffset)
  const expected = articleTextIndex(before.cloneContents()).text.length
  const { text } = articleTextIndex(root)
  // Trimming whitespace in the prefix can change the start by at most one.
  const start = text.slice(expected, expected + exact.length) === exact ? expected : expected + 1
  if (text.slice(start, start + exact.length) !== exact) return
  const end = start + exact.length
  return { exact, start, end, prefix: contextSlice(text, Math.max(0, start - 48), start), suffix: contextSlice(text, end, end + 48) }
}

export function resolveQuote(text: string, quote: CommentQuote): number | undefined {
  if (!quote.exact || quote.exact.length > 1000) return
  const matchesContext = (start: number) => text.slice(0, start).endsWith(quote.prefix) && text.slice(start + quote.exact.length).startsWith(quote.suffix)
  const atSaved = Number.isInteger(quote.start) && quote.start >= 0 && quote.end === quote.start + quote.exact.length && text.slice(quote.start, quote.end) === quote.exact
  if (atSaved && matchesContext(quote.start)) return quote.start
  const candidates: number[] = []
  for (let start = text.indexOf(quote.exact); start >= 0; start = text.indexOf(quote.exact, start + 1)) {
    candidates.push(start)
    if (candidates.length > 2000) return // Avoid pathological repeated-text scans.
  }
  const contextual = candidates.filter(matchesContext)
  if (contextual.length === 1) return contextual[0]
  // One neighboring side may have been edited, but an exact-text match alone
  // cannot prove identity: the original occurrence could have been deleted.
  if (candidates.length === 1) {
    const start = candidates[0]!
    if ((quote.prefix.length >= 8 && text.slice(0, start).endsWith(quote.prefix)) ||
        (quote.suffix.length >= 8 && text.slice(start + quote.exact.length).startsWith(quote.suffix))) return start
  }
  return undefined
}

export function quoteRange(root: HTMLElement, quote: CommentQuote, index = articleTextIndex(root)): Range | undefined {
  const start = resolveQuote(index.text, quote)
  if (start === undefined) return
  const from = index.starts[start], to = index.ends[start + quote.exact.length - 1]
  if (!from || !to) return
  const range = root.ownerDocument.createRange()
  range.setStart(from.node, from.offset); range.setEnd(to.node, to.offset)
  return range
}
