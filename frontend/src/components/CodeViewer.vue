<template>
  <el-dialog :model-value="modelValue" title="代码放大查看" class="ej-dialog code-viewer-dialog" append-to-body destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <div class="code-viewer-controls">
      <span class="code-viewer-language">{{ language || '代码' }}</span>
      <div class="code-viewer-size" role="group" aria-label="代码字号">
        <button type="button" aria-label="缩小代码字号" :disabled="fontSize <= 12" @click="fontSize = Math.max(12, fontSize - 2)">A−</button>
        <button type="button" aria-label="恢复代码默认字号" title="恢复默认字号" @click="fontSize = defaultFontSize">{{ fontSize }}px</button>
        <button type="button" aria-label="放大代码字号" :disabled="fontSize >= 28" @click="fontSize = Math.min(28, fontSize + 2)">A+</button>
      </div>
      <button type="button" :aria-pressed="wrap" @click="wrap = !wrap">自动换行</button>
      <button type="button" @click="copy">复制代码</button>
      <span class="code-copy-status" role="status">{{ copyStatus }}</span>
    </div>
    <pre class="code-viewer-content" :class="{ wrap }" :style="{ fontSize: `${fontSize}px` }" tabindex="0" aria-label="代码内容"><code v-html="highlighted"></code></pre>
    <template #footer><span class="code-viewer-hint">Esc 关闭 · 长行可横向滚动，也可开启自动换行</span><button type="button" class="code-viewer-close" @click="emit('update:modelValue', false)">关闭</button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import hljs from '@/utils/highlight'

const props = defineProps<{ modelValue: boolean; code: string; language: string; initialFontSize: number }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const defaultFontSize = computed(() => Math.max(16, Math.min(28, Math.round(props.initialFontSize))))
const fontSize = ref(16), wrap = ref(false), copyStatus = ref('')
watch(() => props.modelValue, open => {
  if (open) { fontSize.value = defaultFontSize.value; wrap.value = false; copyStatus.value = '' }
})
const highlighted = computed(() => {
  if (props.language && hljs.getLanguage(props.language)) return hljs.highlight(props.code, { language: props.language, ignoreIllegals: true }).value
  return props.code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
})
async function copy() {
  try { await navigator.clipboard.writeText(props.code); copyStatus.value = '已复制' }
  catch { copyStatus.value = '复制失败，请选择代码后手动复制' }
}
</script>

<style>
html .el-dialog.ej-dialog.code-viewer-dialog { width:calc(100% - 32px); max-width:1280px; height:calc(100dvh - 40px); }
html .code-viewer-dialog .el-dialog__body { display:flex; flex-direction:column; gap:14px; overflow:hidden; flex:1; }
html .code-viewer-dialog .el-dialog__footer { display:flex; align-items:center; justify-content:space-between; gap:12px; }
@media(max-width:600px) { html .el-dialog.ej-dialog.code-viewer-dialog { width:calc(100% - 24px); height:calc(100dvh - 24px); } }
</style>
<style scoped>
.code-viewer-controls { display:flex; align-items:center; flex-wrap:wrap; gap:8px; flex-shrink:0; }
.code-viewer-language { font-size:12px; color:var(--ej-muted); margin-right:auto; text-transform:uppercase; }
.code-viewer-size { display:flex; align-items:center; }
.code-viewer-controls button,.code-viewer-close { font:inherit; font-size:12px; border:1px solid var(--ej-line); border-radius:99px; padding:8px 12px; background:var(--ej-surface); color:var(--ej-ink); cursor:pointer; }
.code-viewer-controls button:hover:enabled,.code-viewer-controls button[aria-pressed=true] { background:var(--studio-lime-soft); border-color:var(--ej-ink); }
.code-viewer-controls button:disabled { opacity:.4; cursor:not-allowed; }
.code-viewer-size button { border-radius:0; }
.code-viewer-size button + button { margin-left:-1px; }
.code-viewer-size button:first-child { border-radius:99px 0 0 99px; }
.code-viewer-size button:last-child { border-radius:0 99px 99px 0; }
.code-copy-status { font-size:12px; color:var(--ej-muted); }
.code-copy-status:empty { display:none; }
.code-viewer-content { flex:1; min-height:0; min-width:0; overflow:auto; margin:0; padding:0; border:1px solid var(--ej-ink); border-radius:14px; background:var(--code-bg); color:var(--code-text); font-family:var(--code-font); line-height:1.7; tab-size:4; white-space:pre; scrollbar-width:thin; scrollbar-color:#ffffff55 transparent; overscroll-behavior:contain; }
.code-viewer-content code { display:block; width:max-content; min-width:100%; padding:20px; font:inherit; background:transparent; color:inherit; }
.code-viewer-content.wrap { white-space:pre-wrap; overflow-wrap:anywhere; }
.code-viewer-content.wrap code { width:auto; }
.code-viewer-hint { color:var(--ej-muted); font-size:12px; text-align:left; }
.code-viewer-close { background:var(--ej-ink); color:var(--ej-surface); padding-inline:20px; white-space:nowrap; flex-shrink:0; }
code :deep(:is(.hljs-comment,.hljs-quote,.hljs-meta)) { color:var(--code-muted); font-style:italic; }
code :deep(:is(.hljs-keyword,.hljs-selector-tag,.hljs-section,.hljs-link,.hljs-doctag)) { color:var(--code-keyword); }
code :deep(:is(.hljs-string,.hljs-regexp,.hljs-addition,.hljs-template-tag)) { color:var(--code-string); }
code :deep(:is(.hljs-number,.hljs-literal,.hljs-symbol,.hljs-bullet,.hljs-deletion)) { color:var(--code-number); }
code :deep(:is(.hljs-title,.hljs-function,.hljs-class,.hljs-type,.hljs-built_in,.hljs-name)) { color:var(--code-title); }
code :deep(:is(.hljs-attr,.hljs-attribute,.hljs-params,.hljs-property,.hljs-variable,.hljs-selector)) { color:var(--code-attr); }
code :deep(.hljs-emphasis) { font-style:italic; }
code :deep(.hljs-strong) { font-weight:700; }
@media(max-width:600px) { .code-viewer-language { flex-basis:100%; } .code-viewer-controls { gap:6px; } .code-viewer-controls button { padding:8px 10px; } .code-viewer-content code { padding:14px; } .code-viewer-hint { max-width:200px; font-size:11px; } }
</style>
