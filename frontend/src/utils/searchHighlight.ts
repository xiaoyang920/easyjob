export type TextSegment = { text: string; highlighted: boolean }

/** ES supplies this one marker; every other character stays a Vue text node. */
export function searchSegments(value: string, keyword = '', esMarkers = false): TextSegment[] {
  const output: TextSegment[] = []
  const push = (text: string, highlighted: boolean) => {
    if (!text) return
    const previous = output.at(-1)
    if (previous?.highlighted === highlighted) previous.text += text
    else output.push({ text, highlighted })
  }
  const splitKeyword = (text: string, marked: boolean) => {
    if (marked || !keyword) { push(text, marked); return }
    const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    text.split(new RegExp(`(${escaped})`, 'gi')).forEach((part, i) => push(part, i % 2 === 1))
  }
  const marker = /<span class=(?:'highlight'|"highlight")>|<\/span>/g
  let marked = false, offset = 0
  if (esMarkers) for (const match of value.matchAll(marker)) {
    splitKeyword(value.slice(offset, match.index), marked)
    marked = match[0] !== '</span>'
    offset = match.index! + match[0].length
  }
  splitKeyword(value.slice(offset), marked)
  return output
}
