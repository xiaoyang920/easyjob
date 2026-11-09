import { onBeforeUnmount, onMounted, ref, shallowRef, watch, type Ref } from 'vue'
import { articleReferenceText, selectedArticleReference, type ArticleSelection } from '@/utils/articleReferences'
import { markerBoxes, type MarkerGroup } from '@/utils/commentMarkers'

/** Ranges are tied to this rendered article, never guessed from repeated text. */
export function useArticleReferences(root: Ref<HTMLElement | undefined>) {
  const selection = shallowRef<ArticleSelection>()
  const lines = ref<{ id: string; style: Record<string, string> }[]>([])
  const marked = new Map<string, ArticleSelection>()
  let frame = 0, disposed = false
  let resize: ResizeObserver | undefined, mutation: MutationObserver | undefined
  function valid(value: ArticleSelection) {
    return !!root.value?.contains(value.range.startContainer) && !!root.value.contains(value.range.endContainer)
      && articleReferenceText(value.range.cloneContents()) === value.text
  }
  function schedule() {
    if (disposed || frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      if (!root.value) { lines.value = []; return }
      const groups: MarkerGroup[] = []
      for (const [id, value] of marked) {
        if (!valid(value)) { marked.delete(id); continue }
        groups.push({ key: id, ids: [id], range: value.range, quote: { exact: value.text, start: 0, end: value.text.length, prefix: '', suffix: '' } })
      }
      lines.value = markerBoxes(root.value, groups, scrollX, scrollY).map(box => ({
        id: box.group.key, style: { left: `${box.left}px`, top: `${box.top + box.height + 1}px`, width: `${box.width}px` }
      }))
    })
  }
  function capture() {
    const native = window.getSelection(), element = root.value
    if (!element || !native?.rangeCount) return
    const range = native.getRangeAt(0)
    if (!element.contains(range.startContainer) || !element.contains(range.endContainer)) return
    // A new empty/oversized article selection invalidates the previous one.
    // Moving focus to the question input preserves the last valid article range.
    selection.value = selectedArticleReference(element, native)
  }
  function mark(id: string, text: string, source = selection.value) {
    if (!source || source.text !== text || !valid(source)) return
    marked.set(id, { text, range: source.range.cloneRange() })
    if (marked.size > 32) marked.delete(marked.keys().next().value!)
    schedule()
  }
  function retain(ids: string[]) {
    const keep = new Set(ids)
    for (const id of marked.keys()) if (!keep.has(id)) marked.delete(id)
    schedule()
  }
  function clear() { selection.value = undefined; marked.clear(); lines.value = [] }
  function scrolled(event: Event) { if (event.target !== document && event.target !== window) schedule() }
  watch(root, element => {
    resize?.disconnect(); mutation?.disconnect(); clear()
    if (!element) return
    resize = new ResizeObserver(schedule); resize.observe(element)
    mutation = new MutationObserver(schedule); mutation.observe(element, { childList: true, subtree: true, characterData: true })
  }, { flush: 'post' })
  onMounted(() => {
    document.addEventListener('selectionchange', capture)
    window.addEventListener('resize', schedule); window.addEventListener('scroll', scrolled, true)
    void document.fonts?.ready.then(schedule)
  })
  onBeforeUnmount(() => {
    disposed = true; cancelAnimationFrame(frame)
    resize?.disconnect(); mutation?.disconnect(); clear()
    document.removeEventListener('selectionchange', capture)
    window.removeEventListener('resize', schedule); window.removeEventListener('scroll', scrolled, true)
  })
  return { selection, lines, mark, retain, clear, valid }
}
