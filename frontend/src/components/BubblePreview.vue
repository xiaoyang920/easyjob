<template>
  <div class="bubble-preview" :class="{ compact }" aria-label="聊天气泡预览">
    <template v-if="compact">
      <span class="sample-bubble self" :class="{ 'decoration-bubble': selfStyle }" :style="selfStyle">你好呀～</span>
    </template>
    <template v-else>
      <small>你看到的（自己的消息）</small>
      <div class="sample-row self">
        <span class="sample-bubble self" :class="{ 'decoration-bubble': selfStyle }" :style="selfStyle">好的</span>
      </div>
      <div class="sample-row self">
        <span class="sample-bubble self" :class="{ 'decoration-bubble': selfStyle }" :style="selfStyle">{{ longText }}</span>
      </div>
      <small>对方看到的（自动镜像到左侧）</small>
      <div class="sample-row other">
        <span class="sample-bubble other" :class="{ 'decoration-bubble': otherStyle }" :style="otherStyle">{{ longText }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { chatBubbleStyle, type SpaceArtwork } from '@/utils/spaceSkins'

const props = defineProps<{ bubble?: Pick<SpaceArtwork, 'assets' | 'settings'> | null, compact?: boolean }>()
const longText = '这条消息比较长，用来检查气泡在多行文字下的效果。还可以看看两侧插画是否挡住文字。'
const selfStyle = computed(() => chatBubbleStyle(props.bubble, false))
const otherStyle = computed(() => chatBubbleStyle(props.bubble, true))
</script>

<style scoped>
.bubble-preview { display: grid; gap: 10px; padding: 16px; border: 1px solid var(--ej-line); border-radius: 16px; background: var(--ej-canvas); }
.bubble-preview.compact { place-items: center; min-height: 150px; border: 0; border-radius: 0; }
.bubble-preview small { color: var(--ej-muted); font-size: 12px; }
.sample-row { display: flex; }
.sample-row.self { justify-content: flex-end; }
.sample-bubble { max-width: 78%; font-size: 14px; line-height: 1.5; word-break: break-word; }
/* Default look only; a decorated bubble takes its padding, colours and shape from the global .decoration-bubble rule. */
.sample-bubble:not(.decoration-bubble) { padding: 10px 14px; border-radius: 16px; color: var(--ej-ink); }
.sample-bubble.self:not(.decoration-bubble) { background: var(--ej-accent-soft); border-top-right-radius: 4px; }
.sample-bubble.other:not(.decoration-bubble) { background: var(--ej-surface); border-top-left-radius: 4px; }
</style>
