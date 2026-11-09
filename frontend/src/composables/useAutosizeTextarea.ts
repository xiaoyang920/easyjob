import { nextTick, onBeforeUnmount, onMounted, watch, type Ref } from 'vue'

/** Keep text fields in the document flow, including when opened or resized. */
export function useAutosizeTextarea(element: Ref<HTMLTextAreaElement | undefined>, value: () => string, visible: () => boolean = () => true) {
  let observer: ResizeObserver | undefined, frame = 0, width = -1
  const resize = () => {
    const field = element.value
    if (!field || !visible() || !field.getBoundingClientRect().width) return
    field.style.height = 'auto'
    const style = getComputedStyle(field)
    const borders = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
    field.style.height = `${field.scrollHeight + borders}px`
  }
  const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(resize) }
  watch([element, value, visible], () => void nextTick(schedule), { flush: 'post', immediate: true })
  onMounted(() => {
    window.addEventListener('resize', schedule)
    if (typeof ResizeObserver !== 'undefined') observer = new ResizeObserver(entries => {
      const nextWidth = entries[0]?.contentRect.width ?? 0
      if (nextWidth !== width) { width = nextWidth; schedule() }
    })
    watch(element, (field, old) => { if (old) observer?.unobserve(old); if (field) observer?.observe(field) }, { immediate: true })
  })
  onBeforeUnmount(() => { observer?.disconnect(); window.removeEventListener('resize', schedule); cancelAnimationFrame(frame) })
}
