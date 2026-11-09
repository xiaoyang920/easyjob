export interface ArticleSelection { text: string; range: Range }

/** Preserve prose/code line breaks; omit reader controls from quoted content. */
export function articleReferenceText(source: Node): string {
  const copy = source.cloneNode(true) as HTMLElement | DocumentFragment
  copy.querySelectorAll('script,style,noscript,button,svg,[data-annotation-ignore],.article-code-toolbar').forEach(node => node.remove())
  copy.querySelectorAll('br').forEach(node => node.replaceWith('\n'))
  copy.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,pre,blockquote,tr').forEach(node => node.append('\n'))
  return (copy.textContent || '').replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
}

export function selectedArticleReference(root: HTMLElement, selection = window.getSelection()): ArticleSelection | undefined {
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return
  const range = selection.getRangeAt(0)
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return
  const text = articleReferenceText(range.cloneContents())
  if (!text || text.length > 12000) return
  return { text, range: range.cloneRange() }
}
