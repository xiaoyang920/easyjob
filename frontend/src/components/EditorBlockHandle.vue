<template>
  <div v-if="visible" class="block-handle-ui" :class="{ 'in-fullscreen': fullscreen }">
    <button ref="trigger" type="button" class="block-type-handle" :style="position"
      :aria-label="`段落格式：${label}`" aria-haspopup="menu" :aria-expanded="open"
      title="切换正文或标题" @mousedown.prevent @click="toggle" @keydown="onTriggerKey">
      {{ shortLabel }}<span aria-hidden="true">⠿</span>
    </button>
    <div v-if="open" ref="menu" class="block-type-menu" :style="menuPosition" role="menu" aria-label="切换段落格式" @keydown="onMenuKey">
      <button v-for="option in articleBlockOptions" :key="option.value" type="button" role="menuitemradio"
        :aria-checked="type === option.value" :data-block-type="option.value" @mousedown.prevent @click="apply(option.value)">
        <span class="block-type-symbol" aria-hidden="true">{{ option.value === 'paragraph' ? 'T' : option.short }}</span>{{ option.text }}<span v-if="type === option.value" class="block-type-check" aria-hidden="true">✓</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DomEditor, SlateEditor, SlatePath, SlateRange, SlateTransforms, type IDomEditor } from '@wangeditor/editor'
import { articleBlockOptions, isArticleTextBlock, setArticleBlockStyle } from '@/utils/editorBlockStyle'

const props = defineProps<{ editor: IDomEditor; root?: HTMLElement; fullscreen: boolean }>()
const visible = ref(false), open = ref(false), type = ref('paragraph')
const trigger = ref<HTMLButtonElement>(), menu = ref<HTMLElement>()
const position = ref({ left: '0px', top: '0px' }), menuPosition = ref<Record<string, string>>({})
const otherLabels: Record<string, string> = { 'list-item': '列表', todo: '待办', blockquote: '引用' }
const label = computed(() => articleBlockOptions.find(option => option.value === type.value)?.text || otherLabels[type.value] || '正文')
const shortLabel = computed(() => articleBlockOptions.find(option => option.value === type.value)?.short || label.value)
let target: ReturnType<typeof SlateEditor.pathRef> | undefined
let frame = 0, observer: ResizeObserver | undefined, disposed = false

function close() { open.value = false }
function onTriggerKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); close() }
}
function clear() { close(); visible.value = false; target?.unref(); target = undefined }
function place() {
  const path = target?.current, root = props.root
  if (!path || !root || props.editor.isDestroyed || props.editor.isDisabled()) { clear(); return }
  try {
    const node = SlateEditor.node(props.editor, path)[0]
    if (!isArticleTextBlock(node) || SlateEditor.isEmpty(props.editor, node)) { clear(); return }
    const element = DomEditor.toDOMNode(props.editor, node), rect = element.getBoundingClientRect()
    const body = root.querySelector<HTMLElement>('[data-slate-editor]')!, scroll = root.querySelector('.w-e-scroll')!
    const clip = scroll.getBoundingClientRect(), toolbar = root.querySelector('.toolbar')!.getBoundingClientRect()
    const lineHeight = parseFloat(getComputedStyle(element).lineHeight) || 28
    const text = element.querySelector('[data-slate-string], [data-slate-zero-width]')?.getClientRects()[0]
    const top = text?.height ? text.top + (text.height - 26) / 2 : rect.top + Math.max(0, (lineHeight - 26) / 2)
    const bottom = Math.min(window.innerHeight, clip.bottom)
    if (!rect.width || top < Math.max(0, clip.top, toolbar.bottom) || top + 26 > bottom) { clear(); return }
    // The gutter is outside the text block, so authored text-indent never
    // changes its position and no control overlaps the first character.
    const left = Math.max(4, Math.min(rect.left - 48, body.getBoundingClientRect().right - 48))
    position.value = { left: `${left}px`, top: `${top}px` }
    type.value = DomEditor.getNodeType(node)
    visible.value = true
    const height = Math.min(270, window.innerHeight - 16)
    const menuTop = top + 30 + height <= bottom ? top + 30 : Math.max(8, Math.min(top - height - 4, window.innerHeight - height - 8))
    menuPosition.value = { left: `${Math.min(left, window.innerWidth - 196)}px`, top: `${menuTop}px`, maxHeight: `${height}px` }
  } catch { clear() }
}
function schedule() {
  if (disposed || frame) return
  frame = requestAnimationFrame(() => { frame = 0; place() })
}
function hover(event: PointerEvent) {
  if (open.value || event.buttons || event.pointerType === 'touch') return
  const root = props.root, hit = event.target
  if (!(hit instanceof Element) || !root || hit.closest('.block-handle-ui')) return
  const body = root.querySelector<HTMLElement>('[data-slate-editor]')
  if (!body || !body.contains(hit) || props.editor.isDisabled()) { clear(); return }
  let block: Element | null = hit === body ? null : hit
  while (block && block.parentElement !== body) block = block.parentElement
  // Keep the short path from the text to its handle, but not the entire blank canvas.
  if (!block) {
    const bounds = trigger.value?.getBoundingClientRect()
    if (!bounds || event.clientX < bounds.left - 6 || event.clientX > bounds.right + 8 || event.clientY < bounds.top - 6 || event.clientY > bounds.bottom + 6) clear()
    return
  }
  try {
    const node = DomEditor.toSlateNode(props.editor, block as HTMLElement)
    if (!isArticleTextBlock(node) || props.editor.isVoid(node) || SlateEditor.isEmpty(props.editor, node)) { clear(); return }
    const path = DomEditor.findPath(props.editor, node)
    if (path.length !== 1) { clear(); return }
    if (!target?.current || !SlatePath.equals(target.current, path)) {
      target?.unref(); target = SlateEditor.pathRef(props.editor, path)
    }
    schedule()
  } catch { clear() }
}
function toggle(event: MouseEvent) {
  if (open.value) { close(); return }
  place()
  if (!visible.value) return
  props.editor.hidePanelOrModal()
  open.value = true
  if (!event.detail) void nextTick(() => menu.value?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus())
}
function apply(value: string) {
  const path = target?.current, editor = props.editor
  if (!path || editor.isDisabled()) { clear(); return }
  try {
    const node = SlateEditor.node(editor, path)[0]
    if (!isArticleTextBlock(node)) { clear(); return }
    const selection = editor.selection
    const keepCaret = selection && SlateRange.isCollapsed(selection) && SlatePath.isAncestor(path, selection.anchor.path) ? selection : null
    editor.focus()
    SlateTransforms.select(editor, keepCaret || SlateEditor.start(editor, path))
    setArticleBlockStyle(editor, value, path)
    close()
    void nextTick(schedule)
  } catch { clear() }
}
function onMenuKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); trigger.value?.focus(); return }
  if (event.key === 'Tab') { close(); return }
  if (!['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return
  event.preventDefault(); event.stopPropagation()
  const buttons = [...(menu.value?.querySelectorAll<HTMLButtonElement>('button') || [])]
  const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
  buttons[next]?.focus()
}
function outside(event: Event) {
  if (!(event.target instanceof Element) || !event.target.closest('.block-handle-ui') || !props.root?.contains(event.target)) clear()
}
function leave() { if (!open.value) clear() }
function onScroll(event: Event) {
  if (event.target instanceof Element && event.target.closest('.block-type-menu')) return
  close(); schedule()
}
const changed = () => { if (target) void nextTick(schedule) }
watch(() => props.fullscreen, clear)
onMounted(() => {
  props.root?.addEventListener('pointermove', hover)
  props.root?.addEventListener('pointerleave', leave)
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
  window.addEventListener('scroll', onScroll, true)
  window.addEventListener('resize', onScroll)
  props.editor.on('change', changed)
  observer = new ResizeObserver(schedule)
  if (props.root) observer.observe(props.root)
  const body = props.root?.querySelector('[data-slate-editor]')
  if (body) observer.observe(body)
})
onBeforeUnmount(() => {
  disposed = true; clear(); cancelAnimationFrame(frame); observer?.disconnect()
  props.root?.removeEventListener('pointermove', hover)
  props.root?.removeEventListener('pointerleave', leave)
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', outside)
  window.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', onScroll)
  props.editor.off('change', changed)
})
</script>

<style scoped>
.block-type-handle{position:fixed;z-index:40;display:flex;align-items:center;justify-content:center;gap:3px;width:44px;height:26px;padding:0;border:1px solid var(--ej-line,#dedbd2);border-radius:6px;background:var(--ej-surface,#fffdf7);color:var(--ej-muted,#777);font-family:inherit;font-size:11px;font-weight:600;line-height:1;cursor:pointer;user-select:none}
.block-type-handle>span{font-size:14px;color:#999;font-weight:400}
.block-type-handle:hover,.block-type-handle[aria-expanded=true]{background:var(--studio-lime-soft,#edf8cb);color:var(--ej-ink,#171714);border-color:#b4c77c}
.block-type-menu{position:fixed;z-index:600;overflow:auto;width:188px;padding:6px;border:1px solid var(--ej-line,#dedbd2);border-radius:10px;background:var(--ej-surface,#fffdf7);box-shadow:0 8px 28px #0002;box-sizing:border-box}
.block-type-menu button{display:flex;align-items:center;gap:10px;width:100%;min-height:38px;padding:8px;border:0;border-radius:6px;background:transparent;color:var(--ej-ink,#171714);font:inherit;font-size:13px;text-align:left;cursor:pointer}
.block-type-menu button:hover,.block-type-menu button:focus-visible{background:var(--studio-lime-soft,#edf8cb)}
.block-type-menu button[aria-checked=true]{font-weight:700}
.block-type-symbol{width:26px;color:var(--ej-muted,#777);font-size:12px}.block-type-check{margin-left:auto}
.block-type-handle:focus-visible{outline:2px solid #7e9b28;outline-offset:2px}
.in-fullscreen .block-type-handle{z-index:4100}.in-fullscreen .block-type-menu{z-index:4110}
</style>
