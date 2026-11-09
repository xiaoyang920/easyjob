import { computed, onBeforeUnmount, ref, watch } from 'vue'

export function useResizablePanelWidth(options: { storageKey: string; defaultWidth: number; reservedWidth?: number }) {
  const minimum = 360, maximumLimit = 800
  let saved = options.defaultWidth
  try {
    const value = Number(localStorage.getItem(options.storageKey))
    if (Number.isFinite(value) && value >= minimum && value <= maximumLimit) saved = value
  } catch { /* Keep resizing available when browser storage is disabled. */ }
  const preferredWidth = ref(saved)
  const viewportWidth = ref(window.innerWidth)
  const maximum = computed(() => Math.max(minimum, Math.min(maximumLimit, viewportWidth.value - (options.reservedWidth ?? 632))))
  const width = computed({
    get: () => Math.max(minimum, Math.min(maximum.value, preferredWidth.value)),
    set: (value: number) => {
      if (Number.isFinite(value)) preferredWidth.value = Math.round(Math.max(minimum, Math.min(maximum.value, value)))
    }
  })
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  function save() {
    saveTimer = undefined
    try { localStorage.setItem(options.storageKey, String(preferredWidth.value)) } catch { /* Session resizing still works. */ }
  }
  watch(preferredWidth, () => {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(save, 200)
  })
  function resize() { viewportWidth.value = window.innerWidth }
  window.addEventListener('resize', resize)
  onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    if (saveTimer !== undefined) { clearTimeout(saveTimer); save() }
  })
  return { width, minimum, maximum, viewportWidth }
}
