<template>
  <div class="panel-resize-handle" :class="{ 'is-resizing': resizing }" role="separator" tabindex="0" aria-orientation="vertical"
    :aria-label="label" :aria-controls="controls" :aria-valuemin="minimum" :aria-valuemax="maximum" :aria-valuenow="width" :aria-valuetext="`${width} 像素`"
    title="拖动调整宽度，双击恢复默认；方向键微调"
    @pointerdown="start" @pointermove="move" @pointerup="stop" @pointercancel="stop" @lostpointercapture="stop"
    @keydown="keydown" @dblclick="update(defaultWidth)"></div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
const props = withDefaults(defineProps<{ width: number; minimum: number; maximum: number; defaultWidth: number; enabled?: boolean; label: string; controls: string }>(), { enabled: true })
const emit = defineEmits<{ 'update:width': [value: number]; resizing: [value: boolean] }>()
const resizing = ref(false)
let drag: { element: HTMLElement; pointer: number; x: number; width: number } | undefined
function update(value: number) { if (props.enabled && Number.isFinite(value)) emit('update:width', Math.max(props.minimum, Math.min(props.maximum, value))) }
function start(event: PointerEvent) {
  if (!props.enabled || !event.isPrimary || event.button !== 0) return
  event.preventDefault()
  const element = event.currentTarget as HTMLElement
  drag = { element, pointer: event.pointerId, x: event.clientX, width: props.width }
  element.focus({ preventScroll: true })
  element.setPointerCapture(event.pointerId)
  resizing.value = true
  document.documentElement.classList.add('ej-panel-resizing')
  emit('resizing', true)
}
function move(event: PointerEvent) { if (drag && event.pointerId === drag.pointer) update(drag.width + drag.x - event.clientX) }
function stop() {
  const previous = drag
  drag = undefined
  resizing.value = false
  document.documentElement.classList.remove('ej-panel-resizing')
  if (previous?.element.hasPointerCapture(previous.pointer)) previous.element.releasePointerCapture(previous.pointer)
  emit('resizing', false)
}
function keydown(event: KeyboardEvent) {
  const step = event.shiftKey ? 50 : 20
  const values: Record<string, number> = { ArrowLeft: props.width + step, ArrowRight: props.width - step, Home: props.minimum, End: props.maximum, Enter: props.defaultWidth }
  if (!(event.key in values)) return
  event.preventDefault(); event.stopPropagation(); update(values[event.key]!)
}
watch(() => props.enabled, enabled => { if (!enabled) stop() })
onBeforeUnmount(stop)
</script>
<style scoped>
.panel-resize-handle{position:absolute;z-index:2;left:0;top:20px;bottom:20px;width:12px;cursor:col-resize;touch-action:none;outline:none}
.panel-resize-handle::after{content:'';position:absolute;left:3px;top:50%;width:3px;height:44px;transform:translateY(-50%);border-radius:99px;background:var(--ej-line);transition:background .15s}
.panel-resize-handle:hover::after,.panel-resize-handle:focus-visible::after,.panel-resize-handle.is-resizing::after{width:4px;background:var(--ej-ink)}
.panel-resize-handle:focus-visible::after{box-shadow:0 0 0 3px var(--studio-lime,#cbff46)}
:global(html.ej-panel-resizing),:global(html.ej-panel-resizing *){cursor:col-resize!important;user-select:none!important}
</style>
