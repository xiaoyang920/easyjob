<template>
  <!-- 无封面文章的占位：斜纹纸面 + 一个描边大字，颜色取自外层卡片的 --card-paper -->
  <div class="cover-glyph" aria-hidden="true">
    <span v-if="label" class="cover-glyph-label">{{ label }}</span>
    <span class="cover-glyph-char">{{ glyph }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { nameInitial } from '@/utils/avatar'

// title 需为纯文本（调用方先去掉高亮等 HTML 标记）；label 一般是分类名
const props = defineProps<{ title: string; label?: string }>()

// 优先取分类名首字，其次标题里的第一个文字
const glyph = computed(() => nameInitial(props.label) || nameInitial(props.title) || 'E')
</script>

<style>
#app .cover-glyph {
  position: relative; width: 100%; height: 100%; overflow: hidden;
  background-color: var(--card-paper, var(--studio-lime-soft));
  background-image: repeating-linear-gradient(135deg, #11110f12 0 1px, transparent 1px 13px);
}
#app .cover-glyph-char {
  position: absolute; right: 10%; bottom: -.2em;
  font-size: var(--cover-glyph-size, 116px); font-weight: 850; line-height: 1; letter-spacing: -.04em;
  color: var(--ej-surface); -webkit-text-stroke: 2px var(--ej-ink); text-shadow: 4px 4px 0 var(--ej-ink);
  user-select: none; transition: transform 450ms var(--studio-spring);
}
#app .cover-glyph-label {
  position: absolute; left: 16px; top: 16px; max-width: calc(100% - 32px);
  padding: 4px 10px; border: 1px solid var(--ej-ink); border-radius: 999px; background: var(--ej-surface);
  color: var(--ej-ink); font-size: 10px; font-weight: 800; letter-spacing: .08em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
@media (prefers-reduced-motion: reduce) { #app .cover-glyph-char { transition: none; } }
</style>
