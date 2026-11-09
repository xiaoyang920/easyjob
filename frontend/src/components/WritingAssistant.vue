<template>
  <div v-show="open" class="writing-ai-layer" :class="{ 'in-fullscreen': fullscreen, 'is-resizing': resizing }">
    <div v-if="narrow" class="writing-ai-backdrop" aria-hidden="true" @click="emit('close')"></div>
    <ElFocusTrap :trapped="open && narrow" :loop="open && narrow" :focus-trap-el="panel" @release-requested="emit('close')">
      <aside id="writing-ai-panel" ref="panel" class="writing-ai-panel" tabindex="-1" :style="!narrow ? { width: `${panelWidth}px` } : undefined"
        :role="narrow ? 'dialog' : 'complementary'" :aria-modal="narrow ? true : undefined" aria-label="AI 写作助手"
        @keydown.esc.stop.prevent="emit('close')">
        <div v-if="!narrow" class="writing-ai-resizer" role="separator" tabindex="0" aria-orientation="vertical"
          aria-label="调整 AI 写作助手宽度" aria-controls="writing-ai-panel"
          :aria-valuemin="resizeMinimum" :aria-valuemax="resizeMaximum" :aria-valuenow="panelWidth" :aria-valuetext="`${panelWidth} 像素`"
          title="拖动调整宽度，双击恢复默认；方向键微调"
          @pointerdown="startResize" @pointermove="moveResize" @pointerup="stopResize" @pointercancel="stopResize" @lostpointercapture="stopResize"
          @keydown="resizeWithKeyboard" @dblclick="resetWidth"></div>
        <AiChat ref="chat" embedded writing :writing-scope="conversationScope" :get-editor-context="() => contextLinked ? getEditorContext() : null" @close="emit('close')" @login-required="emit('loginRequired')" @reference-requested="quoteReference" @reference-ready="flushSelectionRequest"
          @reference-attached="(id, text) => emit('referenceAttached', id, text)" @references-changed="ids => emit('referencesChanged', ids)">
          <template #context-tools>
            <div class="writing-context-bar"><span>{{ contextLinked ? '已关联当前文章 · 提问时读取最新内容' : '未关联文章，仅进行对话' }}</span>
              <button type="button" :aria-pressed="contextLinked" @click="contextLinked = !contextLinked">{{ contextLinked ? '取消关联' : '关联文章' }}</button></div>
          </template>
          <template #message-tools="{ message }">
            <EditorEditReview v-for="proposal in message.editorEdits || []" :key="proposal.id" :proposal="proposal" :apply-edit="applyEdit" :undo-edit="undoEdit" />
          </template>
        </AiChat>
      </aside>
    </ElFocusTrap>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ElFocusTrap from 'element-plus/es/components/focus-trap/index.mjs'
import { ElMessage } from 'element-plus'
import AiChat from '@/views/AiChat.vue'
import EditorEditReview from '@/components/EditorEditReview.vue'
import type { EditorSnapshot, EditorProposal, EditOutcome } from '@/utils/editorTools'
import type { WritingReferenceKind, SelectionReferenceRequest } from '@/utils/writingReferences'
import { defaultWritingAssistantWidth } from '@/composables/useWritingAssistantWidth'

const props = withDefaults(defineProps<{
  open: boolean
  fullscreen: boolean
  width?: number
  minWidth?: number
  maxWidth?: number
  conversationScope: string
  getDraft: () => { title: string; summary: string; html: string; selection?: string }
  getEditorContext: () => EditorSnapshot | null
  applyEdit: (proposal: EditorProposal) => EditOutcome
  undoEdit: (proposal: EditorProposal) => EditOutcome
  selectionRequest?: SelectionReferenceRequest | null
}>(), { width: defaultWritingAssistantWidth, minWidth: 360, maxWidth: 800 })
const emit = defineEmits<{ close: []; loginRequired: []; selectionAttached: [id: string]; referenceAttached: [id: string, text: string]; referencesChanged: [ids: string[]]; 'update:width': [width: number] }>()
const panel = ref<HTMLElement>()
const chat = ref<InstanceType<typeof AiChat>>()
const narrow = ref(window.innerWidth < 1200)
const contextLinked = ref(true)
// Open tabs can hot-load this child while still running the previous parent.
// Missing/invalid dimensions must never turn into an intrinsic content width.
const resizeMinimum = computed(() => Number.isFinite(props.minWidth) ? Math.max(360, Math.min(800, props.minWidth)) : 360)
const resizeMaximum = computed(() => Number.isFinite(props.maxWidth) ? Math.max(resizeMinimum.value, Math.min(800, props.maxWidth)) : 800)
function boundedWidth(value: number) { return Math.max(resizeMinimum.value, Math.min(resizeMaximum.value, Number.isFinite(value) ? value : defaultWritingAssistantWidth)) }
const panelWidth = computed(() => boundedWidth(props.width))
const resizing = ref(false)
let drag: { element: HTMLElement; pointerId: number; x: number; width: number } | undefined
function startResize(event: PointerEvent) {
  if (event.button !== 0 || !event.isPrimary || narrow.value) return
  event.preventDefault()
  const element = event.currentTarget as HTMLElement
  drag = { element, pointerId: event.pointerId, x: event.clientX, width: panelWidth.value }
  element.focus({ preventScroll: true })
  element.setPointerCapture(event.pointerId)
  resizing.value = true
  document.documentElement.classList.add('writing-ai-resizing')
}
function moveResize(event: PointerEvent) {
  if (!drag || event.pointerId !== drag.pointerId) return
  emit('update:width', boundedWidth(drag.width + drag.x - event.clientX))
}
function stopResize() {
  const previous = drag
  drag = undefined
  resizing.value = false
  document.documentElement.classList.remove('writing-ai-resizing')
  if (previous?.element.hasPointerCapture(previous.pointerId)) previous.element.releasePointerCapture(previous.pointerId)
}
function resetWidth() { emit('update:width', boundedWidth(defaultWritingAssistantWidth)) }
function resizeWithKeyboard(event: KeyboardEvent) {
  const step = event.shiftKey ? 50 : 20
  let value: number
  switch (event.key) {
    case 'ArrowLeft': value = panelWidth.value + step; break
    case 'ArrowRight': value = panelWidth.value - step; break
    case 'Home': value = resizeMinimum.value; break
    case 'End': value = resizeMaximum.value; break
    case 'Enter': value = defaultWritingAssistantWidth; break
    default: return
  }
  event.preventDefault()
  event.stopPropagation()
  emit('update:width', boundedWidth(value))
}
watch(() => props.open, open => { if (!open) stopResize() })
let handledSelectionId = ''
let focusWhenReady = false
function quoteReference(kind: WritingReferenceKind) {
  try { if (kind === 'selection') quoteSelection(); else quoteDraft() }
  catch { ElMessage.warning('暂时无法读取编辑器，请稍后重新引用') }
}
function quoteSelection() {
  const text = props.getDraft().selection
  if (!text) { ElMessage.info('先在正文中选中需要讨论或修改的文字'); return }
  if (text.length > 12000) { ElMessage.info('选中文字较长，请缩小到 12000 字以内'); return }
  if (chat.value?.attachReference({ kind: 'selection', text, truncated: false })) contextLinked.value = true
}
function resize() { stopResize(); narrow.value = window.innerWidth < 1200 }
window.addEventListener('resize', resize)
onBeforeUnmount(() => { stopResize(); window.removeEventListener('resize', resize) })
function flushSelectionRequest() {
  const selection = props.selectionRequest
  const unhandled = selection && selection.id !== handledSelectionId
  if (!props.open || !chat.value?.canAttachReference?.() || (!focusWhenReady && !unhandled)) return
  focusWhenReady = false
  if (unhandled) {
    handledSelectionId = selection.id
    if (chat.value.attachReference({ kind: 'selection', text: selection.text, truncated: false })) contextLinked.value = true
    emit('selectionAttached', selection.id)
  }
  chat.value.focusInput()
}
watch([() => props.open, chat, () => props.selectionRequest], async ([open]) => {
  if (!open) { focusWhenReady = false; return }
  focusWhenReady = true
  await nextTick()
  flushSelectionRequest()
}, { immediate: true, flush: 'post' })

function quoteDraft() {
  // Read a fresh snapshot only on request; only plain text enters the prompt.
  const draft = props.getDraft()
  const doc = new DOMParser().parseFromString(draft.html, 'text/html')
  doc.querySelectorAll('script,style,noscript').forEach(node => node.remove())
  doc.querySelectorAll('br').forEach(node => node.replaceWith('\n'))
  doc.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,pre,blockquote,tr').forEach(node => node.append('\n'))
  const body = (doc.body.textContent || '').replace(/\n{3,}/g, '\n\n').trim()
  const text = [draft.title.trim() ? `标题：${draft.title.trim()}` : '', draft.summary.trim() ? `摘要：${draft.summary.trim()}` : '', body ? `正文：\n${body}` : ''].filter(Boolean).join('\n\n')
  if (!text) { ElMessage.info('先写一点标题或正文，再引用给 AI'); return }
  const truncated = text.length > 12000
  if (chat.value?.attachReference({ kind: 'draft', text: text.slice(0, 12000), truncated })) {
    contextLinked.value = true
    if (truncated) ElMessage.info('已引用草稿前 12000 字，可展开查看')
  }
}
</script>

<style scoped>
.writing-ai-layer{position:fixed;inset:0;z-index:2100;pointer-events:none;font-family:var(--ej-font,sans-serif);font-size:14px;line-height:1.6;font-weight:400;color:var(--ej-ink);text-align:left}
.writing-ai-panel{position:absolute;top:88px;right:16px;bottom:16px;width:424px;max-width:min(800px,calc(100% - 24px));min-width:0;overflow:hidden;pointer-events:auto;border:1.5px solid var(--ej-ink);border-radius:20px;background:var(--ej-surface);box-shadow:0 5px 0 #11110f12}
.writing-ai-resizer{position:absolute;z-index:2;left:0;top:20px;bottom:20px;width:12px;cursor:col-resize;touch-action:none;outline:none}
.writing-ai-resizer::after{content:'';position:absolute;left:3px;top:50%;width:3px;height:44px;transform:translateY(-50%);border-radius:99px;background:var(--ej-line);transition:background .15s}
.writing-ai-resizer:hover::after,.writing-ai-resizer:focus-visible::after,.is-resizing .writing-ai-resizer::after{width:4px;background:var(--ej-ink)}
.writing-ai-resizer:focus-visible{background:var(--studio-lime,#cbff46);border-radius:8px}
.is-resizing{pointer-events:auto;cursor:col-resize}
:global(html.writing-ai-resizing),:global(html.writing-ai-resizing *){cursor:col-resize!important;user-select:none!important}
.writing-ai-backdrop{position:absolute;inset:72px 0 0;background:#11110f26;pointer-events:auto}
.writing-context-bar{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 16px;border-bottom:1px solid var(--ej-line);font-size:10px;color:var(--ej-muted);flex-shrink:0}.writing-context-bar button{border:0;background:transparent;color:var(--ej-ink);font:inherit;cursor:pointer;white-space:nowrap;padding:4px}
.in-fullscreen .writing-ai-panel{top:64px;bottom:16px}
.in-fullscreen .writing-ai-backdrop{inset:64px 0 0}
@media(max-width:1199px){.writing-ai-panel{width:440px;top:88px;bottom:12px;right:12px}}
@media(max-width:767px){.writing-ai-panel{top:72px;width:calc(100% - 24px)}.writing-ai-backdrop{top:60px}}
@media(max-height:540px){.writing-ai-panel{top:76px;bottom:6px}.in-fullscreen .writing-ai-panel{top:62px;bottom:6px}}
</style>
