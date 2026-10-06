export type SourceLink = { id: string; articleId?: string; url?: string }

function sourceHref(source: SourceLink): string | null {
  if (source.articleId && /^\d+$/.test(source.articleId)) return `/article/${source.articleId}`
  try {
    const url = new URL(source.url || '')
    if (!['http:', 'https:'].includes(url.protocol)) return null
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
      return `<a class="inline-citation" href="${attribute(link.href)}" target="_blank" rel="noopener noreferrer">[${link.number}]</a>`
    })
  }).join('')
}
