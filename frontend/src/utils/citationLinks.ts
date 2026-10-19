export type SourceLink = { id: string; articleId?: string; url?: string; title?: string }

function sourceHref(source: SourceLink): string | null {
  if (source.articleId && /^[1-9]\d*$/.test(source.articleId)) return `/article/${source.articleId}`
  try {
    const url = new URL(source.url || '')
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || /[\x00-\x20\x7f]/.test(source.url || '')) return null
    return url.href
  } catch { return null }
}

function attribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function linkCitations(content: string, sources: SourceLink[] = []): string {
  const links = new Map(sources.map((source, index) => [source.id, { href: sourceHref(source), number: index + 1 }]))
  // Keep source-like text in code and existing Markdown links untouched.
  return content.split(/(```[\s\S]*?(?:```|$)|`[^`]*`|<[^>]*>)/g).map(part => {
    if (part.startsWith('`') || part.startsWith('<')) return part
    return part.replace(/\[((?:[a-z][a-z0-9_]*:)?(?:web)?\d+)\](?!\()/g, (original, id: string) => {
      const link = links.get(id)
      if (!link?.href) return original
      return `<sup class="citation-ref"><a class="inline-citation" href="${attribute(link.href)}" target="_blank" rel="noopener noreferrer">[${link.number}]</a></sup>`
    })
  }).join('')
}

/** Draft prose hides system evidence; keep the original Markdown in the approval payload. */
export function draftBodyHtml(html: string, sources: SourceLink[] = []): string {
  if (!html) return ''
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const ids = new Set(sources.map(source => source.id))
  const reference = /\[((?:[a-z][a-z0-9_]*:)?(?:web)?\d+)\]/g
  const isEvidence = (id: string) => ids.has(id) || id.includes(':')
  const label = /^(?:来源|依据|参考来源|Sources?)\s*[:：]\s*/i
  // Old verified drafts may contain a source-only paragraph added by grounding.
  for (const paragraph of doc.querySelectorAll('p')) {
    if (paragraph.closest('pre,code') || paragraph.querySelector('pre,code') || !label.test(paragraph.textContent?.trim() || '')) continue
    const copy = paragraph.cloneNode(true) as HTMLElement
    const badges = copy.querySelectorAll('.citation-ref,.inline-citation')
    badges.forEach(node => node.remove())
    const content = label.test(copy.textContent?.trim() || '') ? (copy.textContent || '').trim().replace(label, '') : ''
    const markers = [...content.matchAll(reference)]
    if (!(badges.length || markers.length) || markers.some(match => !isEvidence(match[1]!)) || content.replace(reference, '').trim().replace(/[。.;；、,，\s]/g, '')) continue
    const previous = paragraph.previousElementSibling
    if (previous?.tagName === 'P') {
      for (const anchor of previous.querySelectorAll('a')) {
        const href = anchor.getAttribute('href') || ''
        if (/^\^\d+$/.test(anchor.textContent || '') && !sourceHref({ id: '', url: href }) && !href.startsWith('#') && !/^\/article\/[1-9]\d*$/.test(href)) anchor.remove()
      }
    }
    paragraph.remove()
  }
  for (const badge of doc.querySelectorAll('.citation-ref,.inline-citation')) {
    if (badge.closest('pre,code') || badge.querySelector('a[href^="#"]') || badge.matches('a[href^="#"]')) continue
    badge.remove()
  }
  const walker = doc.createTreeWalker(doc.body, 4)
  const texts: Text[] = []
  while (walker.nextNode()) {
    const text = walker.currentNode as Text
    if (!text.parentElement?.closest('a,pre,code,sup')) texts.push(text)
  }
  for (const text of texts) text.data = text.data.replace(reference, (marker, id: string) => isEvidence(id) ? '' : marker)
  return doc.body.innerHTML
}

/** Call after Markdown rendering and sanitation. Code and authored links stay intact. */
export function formatCitationHtml(html: string, sources: SourceLink[] = [], preserveText = false): string {
  if (!html || !/<a\b|<sup\b|\[[a-z][a-z0-9_]*:(?:web)?\d+\]/i.test(html)) return html
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const links = new Map(sources.map((source, index) => [source.id, { ...source, number: index + 1 }]))
  const missing = new Map<string, number>()
  const marker = /\[((?:[a-z][a-z0-9_]*:)?(?:web)?\d+)\]/g
  function badge(id: string): HTMLElement {
    const source = links.get(id)
    const href = source ? sourceHref(source) : null
    if (!source && !missing.has(id)) missing.set(id, sources.length + missing.size + 1)
    const number = source?.number || missing.get(id)!
    const sup = doc.createElement('sup')
    sup.className = 'citation-ref'
    const link = doc.createElement(href ? 'a' : 'span')
    link.className = href ? 'inline-citation' : 'citation-unavailable'
    link.textContent = preserveText ? `[${id}]` : `[${number}]`
    link.title = href ? source?.title || '查看来源' : '这条旧引用未保存有效的来源地址，暂时无法打开'
    if (href) { link.setAttribute('href', href); link.setAttribute('target', '_blank'); link.setAttribute('rel', 'noopener noreferrer'); link.setAttribute('aria-label', `查看来源 ${number}：${source?.title || '原文'}`) }
    if (preserveText) { link.classList.add('citation-raw-label'); link.setAttribute('data-citation-label', `[${number}]`); link.setAttribute('aria-label', `引用 ${number}，${link.title}`) }
    sup.append(link)
    return sup
  }
  const walker = doc.createTreeWalker(doc.body, 4)
  const texts: Text[] = []
  while (walker.nextNode()) {
    const text = walker.currentNode as Text
    if (!text.parentElement?.closest('a,pre,code,sup,.inline-citation,.citation-unavailable')) texts.push(text)
  }
  for (const text of texts) {
    const matches = [...text.data.matchAll(marker)].filter(match => links.has(match[1]!) || match[1]!.includes(':'))
    if (!matches.length) continue
    const fragment = doc.createDocumentFragment()
    let end = 0
    for (const match of matches) {
      fragment.append(doc.createTextNode(text.data.slice(end, match.index)), badge(match[1]!))
      end = match.index! + match[0].length
    }
    fragment.append(doc.createTextNode(text.data.slice(end)))
    text.replaceWith(fragment)
  }
  for (const anchor of doc.querySelectorAll<HTMLAnchorElement>('a')) {
    if (anchor.closest('pre,code')) continue
    const label = anchor.textContent?.trim() || ''
    const number = label.match(/^\[?\^?(\d+)\]?$/)?.[1]
    if (!number || !(anchor.classList.contains('inline-citation') || anchor.parentElement?.tagName === 'SUP' || /^\[|^\^/.test(label))) continue
    const href = anchor.getAttribute('href') || ''
    const valid = sourceHref({ id: '', url: href }) || (/^\/article\/[1-9]\d*$/.test(href) ? href : null)
    const footnote = href.startsWith('#') && doc.getElementById(href.slice(1))
    let element: HTMLElement = anchor
    if (!valid && !footnote) {
      element = doc.createElement('span')
      element.className = 'citation-unavailable legacy-footnote'
      element.title = '这条旧脚注的来源地址无效，暂时无法打开'
      anchor.replaceWith(element)
    } else {
      anchor.className = 'inline-citation'
      if (!footnote) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer' }
      anchor.title ||= `查看来源 ${number}`
      anchor.setAttribute('aria-label', `查看来源 ${number}：${anchor.title}`)
    }
    element.textContent = preserveText ? label : `[${number}]`
    if (preserveText && label !== `[${number}]`) { element.classList.add('citation-raw-label'); element.setAttribute('data-citation-label', `[${number}]`); element.setAttribute('aria-label', `引用 ${number}，${element.title}`) }
    if (element.parentElement?.tagName !== 'SUP') {
      const sup = doc.createElement('sup'); sup.className = 'citation-ref'
      element.replaceWith(sup); sup.append(element)
    } else element.parentElement.classList.add('citation-ref')
  }
  // Evidence-only paragraphs come from the grounding layer. Present their
  // markers beside the preceding prose, never as internal IDs or source dumps.
  for (const paragraph of doc.querySelectorAll('p')) {
    if (paragraph.closest('pre,code') || !/^(?:来源|依据|参考来源|Sources?)\s*[:：]/i.test(paragraph.textContent?.trim() || '')) continue
    const copy = paragraph.cloneNode(true) as HTMLElement
    copy.querySelectorAll('.citation-ref').forEach(node => node.remove())
    if (!/^(?:来源|依据|参考来源|Sources?)\s*[:：]\s*[。.;；、,，]?\s*$/i.test(copy.textContent?.trim() || '')) continue
    const refs = [...paragraph.querySelectorAll<HTMLElement>('.citation-ref')]
    if (!refs.length) continue
    if (preserveText) {
      // Published quote selectors are validated against stored text. Retain its
      // exact order and offsets; only hide the source label visually.
      paragraph.classList.add('citation-source-line')
      for (const node of [...paragraph.childNodes]) {
        if (node.nodeType !== 3 || !node.textContent?.trim()) continue
        const label = doc.createElement('span'); label.className = 'citation-source-label'; label.textContent = node.textContent; label.setAttribute('aria-hidden', 'true'); node.replaceWith(label)
      }
      continue
    }
    const previous = paragraph.previousElementSibling
    if (previous?.tagName === 'P') {
      previous.querySelectorAll('.legacy-footnote').forEach(node => node.closest('sup')?.remove())
      for (const ref of refs) {
        const identity = (ref.querySelector('a')?.getAttribute('href') || '') + ref.textContent
        if (![...previous.querySelectorAll('.citation-ref')].some(node => (node.querySelector('a')?.getAttribute('href') || '') + node.textContent === identity)) previous.append(ref)
      }
      paragraph.remove()
    } else paragraph.replaceChildren(...refs)
  }
  return doc.body.innerHTML
}
