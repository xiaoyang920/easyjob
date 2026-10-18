import { computed, ref, watch } from 'vue'

const STORAGE_KEY = 'easyjob:article-reading:v1'

export function useArticleReading() {
  let saved: { scale?: unknown; wide?: unknown } = {}
  try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {} } catch { /* Reading also works without storage. */ }
  const scale = ref(typeof saved.scale === 'number' && Number.isInteger(saved.scale) && saved.scale >= 90 && saved.scale <= 150 ? saved.scale : 100)
  const wide = ref(saved.wide === true)
  const style = computed(() => ({ '--article-reading-scale': String(scale.value / 100) }))
  function resize(delta: number) { scale.value = Math.max(90, Math.min(150, scale.value + delta)) }
  watch([scale, wide], () => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ scale: scale.value, wide: wide.value })) } catch { /* Keep the current page usable. */ }
  })
  return { scale, wide, style, resize }
}
