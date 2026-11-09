export const TAB_INDENT_PX = 32
export const MAX_INDENT_PX = 256
export const MAX_BLOCK_DEPTH = 8
export function blockIndentPixels(value: string): number | null {
  const match = value.trim().toLowerCase().match(/^(\d+)px$/)
  if (!match) return null
  const amount = Number(match[1])
  return amount <= MAX_BLOCK_DEPTH * TAB_INDENT_PX && amount % TAB_INDENT_PX === 0 ? amount : null
}
export function indentPixels(value: string): number | null {
  const match = value.trim().toLowerCase().match(/^(\d+)(px|em)?$/)
  if (!match) return null
  const amount = Number(match[1]) * (match[2] === 'em' ? 16 : 1)
  if (!match[2] && amount !== 0) return null
  return amount >= 0 && amount <= MAX_INDENT_PX && amount % 16 === 0 ? amount : null
}
const blocks = new Set(['p','h1','h2','h3','h4','h5','h6','blockquote','li','td','th'])
const tags = new Set([...blocks, 'span','strong','b','em','i','u','s','del','code'])
function color(value: string): boolean {
  if (/^#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})$/.test(value)) return true
  if (/^(black|white|red|green|blue|yellow|gray|grey|orange|purple|transparent)$/.test(value)) return true
  const rgb = value.match(/^(rgb|rgba)\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?))?\s*\)$/)
  return !!rgb && [rgb[2],rgb[3],rgb[4]].every(channel => Number(channel) <= 255)
    && (rgb[1] === 'rgba' ? rgb[5] !== undefined : rgb[5] === undefined)
}
/** Bounded author formatting, including block depth; no URLs, variables or arbitrary layout CSS. */
export function articleTextStyle(tag: string, style: string): string {
  tag = tag.toLowerCase()
  if (!tags.has(tag)) return ''
  const result = new Map<string,string>()
  for (const declaration of style.split(';')) {
    const separator = declaration.indexOf(':')
    if (separator < 0) continue
    const name = declaration.slice(0,separator).trim().toLowerCase(), value = declaration.slice(separator + 1).trim().toLowerCase()
    let allowed = ''
    if (name === 'text-indent' && blocks.has(tag)) {
      const pixels = indentPixels(value)
      if (pixels !== null) allowed = `${pixels}px`
    } else if (name === 'margin-left' && /^(p|h[1-6]|blockquote)$/.test(tag)) {
      const pixels = blockIndentPixels(value)
      if (pixels !== null) allowed = `${pixels}px`
    } else if (name === 'font-size' && /^(?:1\d|[2-6]\d|7[0-2])px$/.test(value)) allowed = value
    else if (['color','background-color'].includes(name) && color(value)) allowed = value
    else if (name === 'line-height' && blocks.has(tag) && /^(?:[12](?:\.\d{1,3})?|3(?:\.0{1,3})?)$/.test(value)) allowed = value
    else if (name === 'text-align' && blocks.has(tag) && /^(left|right|center|justify)$/.test(value)) allowed = value
    if (allowed) result.set(name, allowed)
  }
  return [...result].map(([name,value]) => `${name}: ${value};`).join(' ')
}
/** Upgrade legacy relative indents without touching the rest of the editor HTML. */
export function normalizeEditorIndents(html: string): string {
  if (!/text-indent\s*:[^;"']*em/i.test(html)) return html
  const document = new DOMParser().parseFromString(html, 'text/html')
  for (const element of document.querySelectorAll<HTMLElement>('[style]')) {
    const pixels = indentPixels(element.style.textIndent)
    if (pixels !== null) element.style.textIndent = `${pixels}px`
  }
  return document.body.innerHTML
}
