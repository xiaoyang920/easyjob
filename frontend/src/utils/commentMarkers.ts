import { articleTextIndex, quoteRange, resolveQuote, type CommentQuote } from './commentAnchors.ts'

export interface QuoteMarker { commentId: string; quote: CommentQuote }
export interface MarkerGroup { key: string; ids: string[]; range: Range; quote: CommentQuote }
export interface MarkerBox { group: MarkerGroup; left: number; top: number; width: number; height: number }

/** Resolve one shared text index per article, then group identical current spans. */
export function groupCommentMarkers(root: HTMLElement, markers: QuoteMarker[]): MarkerGroup[] {
  const index = articleTextIndex(root), groups = new Map<string, MarkerGroup>()
  for (const marker of markers) {
    const start = resolveQuote(index.text, marker.quote)
    if (start === undefined) continue
    const key = `${start}:${start + marker.quote.exact.length}`
    const group = groups.get(key)
    if (group) { if (!group.ids.includes(marker.commentId)) group.ids.push(marker.commentId); continue }
    const range = quoteRange(root, marker.quote, index)
    if (range) groups.set(key, { key, ids: [marker.commentId], range, quote: marker.quote })
  }
  return [...groups.values()]
}

/** Document coordinates keep the lines stable during normal page scrolling. */
export function markerBoxes(root: HTMLElement, groups: MarkerGroup[], scrollX: number, scrollY: number): MarkerBox[] {
  const rootRect = root.getBoundingClientRect(), result: MarkerBox[] = []
  type Clip = { left: number; right: number; top: number; bottom: number }
  const rootClip: Clip = { left: rootRect.left, right: rootRect.right, top: rootRect.top, bottom: rootRect.bottom }
  const clips = new Map<Element, Clip>([[root, rootClip]])
  function clipFor(element: Element | null): Clip {
    if (!element || !root.contains(element)) return rootClip
    const known = clips.get(element)
    if (known) return known
    const clip = { ...clipFor(element.parentElement) }, style = root.ownerDocument.defaultView!.getComputedStyle(element)
    const x = /(auto|scroll|hidden|clip)/.test(style.overflowX), y = /(auto|scroll|hidden|clip)/.test(style.overflowY)
    if (x || y) {
      const rect = element.getBoundingClientRect()
      if (x) { clip.left = Math.max(clip.left, rect.left); clip.right = Math.min(clip.right, rect.right) }
      if (y) { clip.top = Math.max(clip.top, rect.top); clip.bottom = Math.min(clip.bottom, rect.bottom) }
    }
    clips.set(element, clip); return clip
  }
  for (const group of groups) {
    const textRects: { rect: DOMRect; clip: Clip }[] = []
    const walker = root.ownerDocument.createTreeWalker(root, 4)
    walker.currentNode = group.range.startContainer
    let node: Node | null = walker.currentNode
    while (node) {
      const text = node as Text
      if (node.nodeType === 3 && !text.parentElement?.closest('.article-code-toolbar,button,script,style,svg,[data-annotation-ignore]')) {
        const part = root.ownerDocument.createRange()
        const from = node === group.range.startContainer ? group.range.startOffset : 0
        const to = node === group.range.endContainer ? group.range.endOffset : text.length
        if (to > from) {
          part.setStart(text, from); part.setEnd(text, to)
          const clip = clipFor(text.parentElement)
          textRects.push(...Array.from(part.getClientRects()).map(rect => ({ rect, clip })))
        }
      }
      if (node === group.range.endContainer) break
      node = walker.nextNode()
    }
    for (const { rect, clip } of textRects) {
      const left = Math.max(clip.left, rect.left), right = Math.min(clip.right, rect.right)
      const top = Math.max(clip.top, rect.top), bottom = Math.min(clip.bottom, rect.bottom)
      if (right > left && bottom > top) result.push({ group, left: left + scrollX, top: top + scrollY, width: right - left, height: bottom - top })
    }
  }
  return result
}

export function markerIdsAt(boxes: MarkerBox[], x: number, y: number): string[] {
  return [...new Set(boxes.filter(box => x >= box.left && x <= box.left + box.width && y >= box.top - 1 && y <= box.top + box.height + 3).flatMap(box => box.group.ids))]
}
