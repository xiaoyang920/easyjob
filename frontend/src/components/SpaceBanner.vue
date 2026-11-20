<template>
  <div class="space-banner" :class="{ 'has-photo': url && url !== failedUrl, 'can-drag': editable && url && url !== failedUrl }"
    :style="{ '--space-banner-ratio': ratio.replace(':', ' / ') }"
    aria-hidden="true" @pointerdown="startDrag" @pointermove="moveDrag" @lostpointercapture="drag = undefined">
    <img v-if="url && url !== failedUrl" :src="url" alt="" draggable="false"
      :style="{ objectPosition: x + '% ' + position + '%' }" @error="failedUrl = url">
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { SpaceBannerView } from '@/utils/spaceSkins'

const props = withDefaults(defineProps<{
  url?: string | null, position?: number, x?: number, ratio?: SpaceBannerView['ratio'], editable?: boolean
}>(), { position: 50, x: 50, ratio: '16:9' })
const emit = defineEmits<{ 'update:position': [value: number], 'update:x': [value: number] }>()
const failedUrl = ref<string | null>()
let drag: {
  pointer: number, x: number, y: number, initialX: number, initialY: number,
  overflowX: number, overflowY: number
} | undefined

function startDrag(event: PointerEvent) {
  if (!props.editable || !props.url || props.url === failedUrl.value || event.button !== 0) return
  const banner = event.currentTarget as HTMLElement
  const image = banner.querySelector('img')
  if (!image?.naturalWidth) return
  const scale = Math.max(banner.clientWidth / image.naturalWidth, banner.clientHeight / image.naturalHeight)
  const overflowX = image.naturalWidth * scale - banner.clientWidth
  const overflowY = image.naturalHeight * scale - banner.clientHeight
  if (overflowX < 1 && overflowY < 1) return
  event.preventDefault()
  banner.setPointerCapture(event.pointerId)
  drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, initialX: props.x, initialY: props.position, overflowX, overflowY }
}

function moveDrag(event: PointerEvent) {
  if (!drag || drag.pointer !== event.pointerId) return
  if (drag.overflowX >= 1) emit('update:x', dragPosition(drag.initialX, event.clientX - drag.x, drag.overflowX))
  if (drag.overflowY >= 1) emit('update:position', dragPosition(drag.initialY, event.clientY - drag.y, drag.overflowY))
}

function dragPosition(initial: number, delta: number, overflow: number) {
  return Math.max(0, Math.min(100, Math.round(initial - delta / overflow * 100)))
}
</script>

<style scoped>
.space-banner {
  position: relative;
  height: 180px;
  overflow: hidden;
  background:
    repeating-linear-gradient(120deg, transparent 0 32px, rgb(255 255 255 / .18) 33px 34px, transparent 35px 57px),
    linear-gradient(110deg, var(--space-banner-start), var(--space-banner-end));
}
.space-banner img { position: absolute; inset: 0; display: block; width: 100%; height: 100%; object-fit: cover; }
.space-banner.can-drag { cursor: grab; touch-action: none; }
.space-banner.can-drag:active { cursor: grabbing; }
.space-banner.has-photo::after {
  content: ''; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(0deg, rgb(0 0 0 / .44), transparent 65%);
}
@media (max-width: 760px) { .space-banner { height: 120px; } }
.space-banner.has-photo { height: auto; aspect-ratio: var(--space-banner-ratio); }
</style>
