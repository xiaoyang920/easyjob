<template>
  <nav ref="navigation" class="editor-toc" :class="{ 'toc-document': documentLayout, 'toc-fullscreen': fullscreen, 'toc-with-panel': sidePanelOpen, 'toc-empty-state': !entries.length, 'is-open': open }"
    aria-label="正文目录" :style="{ '--toc-sticky-top': `${stickyTop}px` }" @keydown.esc="closeFromKeyboard">
    <button ref="toggle" type="button" class="toc-toggle" :aria-expanded="open" :aria-controls="panelId" @click="open = !open">
      <span aria-hidden="true">☰</span> 目录 <span class="toc-count">{{ entries.length }}</span><span class="toc-chevron" aria-hidden="true">⌄</span>
    </button>
    <div :id="panelId" class="toc-panel">
      <div class="toc-heading">目录 <span>{{ entries.length }}</span></div>
      <div ref="list" class="toc-entries">
        <button v-for="entry in entries" :key="entry.key" type="button" class="toc-entry" :title="entry.text"
          :aria-current="active === entry.key ? 'location' : undefined" :style="{ paddingLeft: `${10 + (entry.level - minimumLevel) * 12}px` }"
          @click="navigate(entry)">{{ entry.text }}</button>
        <p v-if="!entries.length" class="toc-empty"><span class="toc-empty-short">暂无标题</span><span class="toc-empty-detail">添加标题后会显示在这里</span></p>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useId, watch } from 'vue'
import type { IDomEditor } from '@wangeditor/editor'

const props = defineProps<{ editor: IDomEditor; root?: HTMLElement; documentLayout: boolean; fullscreen: boolean; sidePanelOpen?: boolean }>()
const emit = defineEmits<{ headingsChange: [count: number] }>()
type Entry = { key: number; text: string; level: number; element: HTMLElement }
const entries = shallowRef<Entry[]>([]), active = ref<number>(), open = ref(false), stickyTop = ref(0)
const navigation = ref<HTMLElement>(), list = ref<HTMLElement>(), toggle = ref<HTMLButtonElement>()
const panelId = `editor-toc-${useId()}`
const minimumLevel = computed(() => Math.min(6, ...entries.value.map(entry => entry.level)))
watch(() => entries.value.length, count => emit('headingsChange', count), { immediate: true })
// DOM identities are presentation-only; the directory never adds IDs or marks to saved content.
const keys = new WeakMap<HTMLElement, number>()
let nextKey = 0, frame = 0, scanNeeded = true, disposed = false, observer: ResizeObserver | undefined

function refresh() {
  frame = 0
  const root = props.root, body = root?.querySelector('[data-slate-editor]')
  if (!root || !body || disposed) return
  if (scanNeeded) {
    scanNeeded = false
    entries.value = [...body.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6')].map(element => {
      if (!keys.has(element)) keys.set(element, ++nextKey)
      return { key: keys.get(element)!, text: element.textContent?.replace(/\uFEFF/g, '').trim() || '未命名标题', level: Number(element.tagName.slice(1)), element }
    })
  }
  const toolbarElement = root.querySelector<HTMLElement>('.toolbar')!, toolbar = toolbarElement.getBoundingClientRect()
  stickyTop.value = (parseFloat(getComputedStyle(toolbarElement).top) || 0) + toolbar.height
  const compactHeight = toggle.value?.getClientRects().length ? toggle.value.offsetHeight : 0
  const top = Math.max(0, toolbar.bottom) + compactHeight + 24
  let current = entries.value[0]?.key
  for (const entry of entries.value) {
    if (entry.element.getBoundingClientRect().top > top) break
    current = entry.key
  }
  if (active.value !== current) {
    active.value = current
    void nextTick(() => {
      const item = list.value?.querySelector<HTMLElement>('[aria-current="location"]'), container = list.value
      if (!item || !container) return
      // Scroll only the directory, never the page or the editor's selection.
      const itemBox = item.getBoundingClientRect(), box = container.getBoundingClientRect()
      if (itemBox.top < box.top) container.scrollTop -= box.top - itemBox.top
      else if (itemBox.bottom > box.bottom) container.scrollTop += itemBox.bottom - box.bottom
    })
  }
}
function schedule() { if (!disposed && !frame) frame = requestAnimationFrame(refresh) }
function changed() { scanNeeded = true; void nextTick(schedule) }
function navigate(entry: Entry) {
  const root = props.root
  if (!root || !entry.element.isConnected) return
  const target = entry.element.getBoundingClientRect()
  const toolbar = root.querySelector('.toolbar')!.getBoundingClientRect()
  if (props.fullscreen) {
    const scroll = root.querySelector<HTMLElement>('.w-e-scroll')!
    scroll.scrollTo({ top: scroll.scrollTop + target.top - scroll.getBoundingClientRect().top - 16, behavior: 'instant' })
  } else {
    const stickyTop = parseFloat(getComputedStyle(root.querySelector('.toolbar')!).top) || 0
    const compactHeight = toggle.value?.getClientRects().length ? toggle.value.offsetHeight : 0
    window.scrollTo({ top: window.scrollY + target.top - stickyTop - toolbar.height - compactHeight - 16, behavior: 'instant' })
  }
  open.value = false
  // Leave the editing caret and undo stack intact; keyboard users retain a visible navigation control.
  if (toggle.value?.getClientRects().length) toggle.value.focus({ preventScroll: true })
  schedule()
}
function closeFromKeyboard(event: KeyboardEvent) {
  if (!open.value) return
  event.preventDefault(); event.stopPropagation(); open.value = false; toggle.value?.focus({ preventScroll: true })
}
function outside(event: Event) {
  if (event.target instanceof Node && !navigation.value?.contains(event.target)) open.value = false
}
function scrolled(event: Event) {
  if (event.target instanceof Node && navigation.value?.contains(event.target)) return
  schedule()
}
watch(() => [props.fullscreen, props.sidePanelOpen], () => { open.value = false; void nextTick(schedule) })
onMounted(() => {
  props.editor.on('change', changed)
  window.addEventListener('scroll', scrolled, true)
  window.addEventListener('resize', schedule)
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
  observer = new ResizeObserver(schedule)
  if (props.root) observer.observe(props.root)
  const toolbar = props.root?.querySelector('.toolbar'), body = props.root?.querySelector('[data-slate-editor]')
  if (toolbar) observer.observe(toolbar)
  if (body) observer.observe(body)
  schedule()
})
onBeforeUnmount(() => {
  disposed = true; cancelAnimationFrame(frame); observer?.disconnect()
  props.editor.off('change', changed)
  window.removeEventListener('scroll', scrolled, true)
  window.removeEventListener('resize', schedule)
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', outside)
})
</script>

<style scoped>
.editor-toc{position:relative;flex:none;z-index:24;min-width:0;border-bottom:1px solid var(--ej-line,#dedbd2);background:var(--ej-surface,#fffdf7);color:var(--ej-ink,#171714)}
.toc-document:not(.toc-fullscreen){position:sticky;top:var(--toc-sticky-top)}
.toc-toggle{display:flex;align-items:center;gap:8px;width:100%;padding:9px 14px;border:0;background:transparent;color:inherit;font:inherit;font-size:12px;text-align:left;cursor:pointer}
.toc-count,.toc-heading span{color:var(--ej-muted,#777);font-size:11px;font-weight:400}.toc-chevron{margin-left:auto}
.toc-panel{display:none;position:absolute;top:100%;left:0;width:min(300px,100%);padding:10px;box-sizing:border-box;border:1px solid var(--ej-line,#dedbd2);border-radius:0 0 10px 10px;background:var(--ej-surface,#fffdf7);box-shadow:0 8px 20px #0001}
.is-open .toc-panel{display:block}
.toc-heading{display:flex;align-items:center;justify-content:space-between;padding:2px 10px 10px;font-size:12px;font-weight:700}
.toc-entries{max-height:min(50dvh,420px);overflow:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:#1112 transparent}
.toc-entry{display:block;width:100%;overflow:hidden;padding:7px 10px;border:0;border-left:2px solid transparent;border-radius:4px;background:transparent;color:var(--ej-muted,#777);font:inherit;font-size:12px;line-height:1.5;text-overflow:ellipsis;white-space:nowrap;text-align:left;cursor:pointer}
.toc-entry:hover,.toc-entry:focus-visible{background:#11110f08;color:var(--ej-ink,#171714)}
.toc-entry[aria-current]{border-left-color:#8cae2e;background:var(--studio-lime-soft,#edf8cb);color:var(--ej-ink,#171714);font-weight:600}
.toc-entry:focus-visible,.toc-toggle:focus-visible{outline:2px solid #7e9b28;outline-offset:-2px}
.toc-empty{margin:0;padding:8px 10px;color:var(--ej-muted,#777);font-size:12px;line-height:1.8}
.toc-empty-short{display:none}
@media(min-width:1200px){
  .toc-document:not(.toc-fullscreen){position:absolute;top:0;bottom:0;left:-184px;width:168px;border:0;background:transparent}
  .toc-document:not(.toc-fullscreen) .toc-toggle{display:none}
  .toc-document:not(.toc-fullscreen) .toc-panel{display:block;position:sticky;top:var(--document-toolbar-top,136px);width:100%;padding:8px 0;border:0;border-radius:0;background:transparent;box-shadow:none}
  .toc-document:not(.toc-fullscreen) .toc-entries{max-height:calc(100dvh - var(--document-toolbar-top,136px) - 72px)}
}
@media(min-width:1000px){
  .toc-fullscreen{position:relative;left:auto;top:auto;bottom:auto;width:auto;min-height:0;overflow:hidden;border:0;border-right:1px solid var(--ej-line,#dedbd2);background:var(--ej-canvas,#f2efe7)}
  .toc-fullscreen .toc-toggle{display:none}
  .toc-fullscreen .toc-panel{display:flex;flex-direction:column;position:static;width:100%;height:100%;min-height:0;padding:20px 10px;border:0;background:transparent;box-shadow:none}
  .toc-fullscreen .toc-heading{flex:none;font-size:13px}
  .toc-fullscreen .toc-entries{flex:1;max-height:none;min-height:0}
  .toc-fullscreen .toc-entry{font-size:13px}
  .toc-fullscreen.toc-empty-state .toc-panel{padding:20px 6px}
  .toc-fullscreen.toc-empty-state .toc-heading{justify-content:center;padding:2px 0 10px}
  .toc-fullscreen.toc-empty-state .toc-heading span{display:none}
  .toc-fullscreen.toc-empty-state .toc-empty{padding:8px 0;text-align:center;font-size:11px}
  .toc-fullscreen .toc-empty-short{display:inline}
  .toc-fullscreen .toc-empty-detail{display:none}
}
@media(min-width:1200px) and (max-width:1599px){
  .toc-with-panel{position:relative;top:auto;bottom:auto;left:auto;width:auto;overflow:visible;border:0;border-bottom:1px solid var(--ej-line,#dedbd2);background:var(--ej-surface,#fffdf7)}
  .toc-with-panel.toc-document:not(.toc-fullscreen){position:sticky;top:var(--toc-sticky-top);bottom:auto;left:auto;width:auto;border-bottom:1px solid var(--ej-line,#dedbd2);background:var(--ej-surface,#fffdf7)}
  .toc-with-panel .toc-toggle,.toc-with-panel.toc-document:not(.toc-fullscreen) .toc-toggle{display:flex}
  .toc-with-panel .toc-panel,.toc-with-panel.toc-document:not(.toc-fullscreen) .toc-panel{display:none;position:absolute;top:100%;width:min(300px,100%);height:auto;padding:10px;border:1px solid var(--ej-line,#dedbd2);border-radius:0 0 10px 10px;background:var(--ej-surface,#fffdf7);box-shadow:0 8px 20px #0001}
  .toc-with-panel.is-open .toc-panel{display:block}
  .toc-with-panel .toc-entries,.toc-with-panel.toc-document:not(.toc-fullscreen) .toc-entries{max-height:min(50dvh,420px)}
  .toc-with-panel.toc-fullscreen .toc-entry{font-size:12px}
  .toc-with-panel.toc-fullscreen.toc-empty-state .toc-panel{padding:10px}
  .toc-with-panel.toc-fullscreen .toc-empty-short{display:none}
  .toc-with-panel.toc-fullscreen .toc-empty-detail{display:inline}
}
</style>
