<template>
  <div class="writing-reference" :class="{ 'is-removable': removable }">
    <details>
      <summary :aria-label="`查看引用：${referenceLabel(reference.kind)}${index ? ` ${index}` : ''}`">
        <span class="reference-at" aria-hidden="true">@</span>
        <strong>{{ referenceLabel(reference.kind) }}{{ index ? ` ${index}` : '' }}</strong>
        <span class="reference-snippet">{{ reference.text.replace(/\s+/g, ' ').slice(0, 42) }}</span>
        <span class="reference-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="reference-preview">
        <p>{{ reference.text.length }} 字<span v-if="reference.truncated"> · 长文节选，仅引用前 12000 字</span></p>
        <pre>{{ reference.text }}</pre>
      </div>
    </details>
    <button v-if="removable" type="button" class="reference-remove" :aria-label="`移除引用${index ? ` ${index}` : ''}`" title="移除引用" :disabled="disabled" @click="$emit('remove')">×</button>
  </div>
</template>

<script setup lang="ts">
import { referenceLabel, type WritingReference } from '@/utils/writingReferences'
defineProps<{ reference: WritingReference; index?: number; removable?: boolean; disabled?: boolean }>()
defineEmits<{ remove: [] }>()
</script>

<style scoped>
.writing-reference{position:relative;min-width:0;max-width:100%;border:1px solid var(--ej-line,#d4d0c7);border-radius:12px;background:var(--ej-surface,#fffdf7);color:var(--ej-ink,#171714);font-size:12px;line-height:1.5;text-align:left}
.writing-reference details{min-width:0}.writing-reference summary{display:flex;align-items:center;gap:7px;min-height:38px;padding:8px 10px;cursor:pointer;list-style:none;user-select:none}.writing-reference summary::-webkit-details-marker{display:none}
.is-removable summary{padding-right:36px}.writing-reference summary:focus-visible,.reference-remove:focus-visible{outline:2px solid var(--ej-ink,#171714);outline-offset:2px;border-radius:10px}
.reference-at{display:grid;place-items:center;flex-shrink:0;width:21px;height:21px;border-radius:6px;background:var(--studio-lime,#d0ff45);font-size:14px;font-weight:750;color:#171714}
.writing-reference strong{flex-shrink:0;font-size:12px;font-weight:650}.reference-snippet{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ej-muted,#77766d);font-size:11px}.reference-chevron{margin-left:auto;flex-shrink:0;color:var(--ej-muted,#77766d)}
.reference-preview{padding:0 12px 12px}.reference-preview p{margin:0 0 7px;font-size:10px;color:var(--ej-muted,#77766d)}.reference-preview pre{max-height:136px;overflow:auto;margin:0;padding:10px;border-radius:8px;background:var(--ej-canvas,#f2efe7);font:inherit;font-size:11px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;user-select:text}
.reference-remove{position:absolute;right:6px;top:7px;width:26px;height:26px;padding:0;border:0;border-radius:7px;background:transparent;color:var(--ej-muted,#77766d);font:inherit;font-size:20px;line-height:1;cursor:pointer}.reference-remove:hover{background:var(--ej-canvas,#f2efe7);color:var(--ej-ink,#171714)}.reference-remove:disabled{opacity:.4;cursor:default}
</style>
