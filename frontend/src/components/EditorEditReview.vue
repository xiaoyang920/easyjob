<template>
  <section class="editor-edit-review" aria-label="待确认修改">
    <header><strong>{{ labels[proposal.target] }}修改建议</strong><span>{{ state === 'applied' ? '已应用' : state === 'ignored' ? '已忽略' : '等待确认' }}</span></header>
    <p v-if="proposal.explanation">{{ proposal.explanation }}</p>
    <details><summary>查看原文</summary><pre class="edit-before">{{ originalText || '（空）' }}</pre></details>
    <div class="edit-after"><span>修改后</span><pre>{{ proposal.after }}</pre></div>
    <div class="edit-review-actions">
      <button type="button" :disabled="state !== 'pending'" @click="apply">应用修改</button>
      <button type="button" class="edit-ignore" :disabled="state !== 'pending'" @click="state = 'ignored'">忽略</button>
      <button v-if="state === 'applied'" type="button" class="edit-ignore" @click="undo">撤销本次修改</button>
    </div>
    <p v-if="notice" class="edit-notice" role="status">{{ notice }}</p>
  </section>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { EditorProposal, EditOutcome } from '@/utils/editorTools'
const props = defineProps<{ proposal: EditorProposal; applyEdit: (proposal: EditorProposal) => EditOutcome; undoEdit: (proposal: EditorProposal) => EditOutcome }>()
const labels = { title: '标题', summary: '摘要', body: '正文', selection: '选中文字' }
const state = ref<'pending' | 'applied' | 'ignored' | 'error'>('pending')
const notice = ref('')
const originalText = computed(() => props.proposal.target === 'body'
  ? new DOMParser().parseFromString(props.proposal.before.replace(/<\/(?:p|div|h[1-6]|li|pre)>/gi, '$&\n'), 'text/html').body.textContent || ''
  : props.proposal.before)
function apply() {
  const result = props.applyEdit(props.proposal)
  notice.value = result.message
  state.value = result.ok ? 'applied' : 'error'
}
function undo() {
  const result = props.undoEdit(props.proposal)
  notice.value = result.message
  if (result.ok) state.value = 'ignored'
}
</script>
<style scoped>
.editor-edit-review{margin-top:16px;border:1px solid var(--ej-ink);border-radius:14px;background:var(--ej-surface);overflow:hidden;font-size:12px;color:var(--ej-ink)}
header{display:flex;justify-content:space-between;gap:8px;padding:12px;border-bottom:1px solid var(--ej-line);background:var(--studio-lime-soft)}header span{color:var(--ej-muted);font-size:11px}
p,details,.edit-after{margin:12px}summary{cursor:pointer;color:var(--ej-muted)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8;max-height:260px;overflow:auto;margin:8px 0}.edit-before{color:var(--ej-muted)}.edit-after>span{font-size:11px;color:var(--ej-muted)}
.edit-review-actions{display:flex;gap:8px;padding:0 12px 12px}.edit-review-actions button{padding:7px 12px;border:1px solid var(--ej-ink);border-radius:99px;background:var(--ej-ink);color:var(--ej-surface);font:inherit;cursor:pointer}.edit-review-actions .edit-ignore{background:transparent;color:var(--ej-ink)}button:disabled{opacity:.45;cursor:default}.edit-notice{font-size:11px;color:var(--ej-muted)}
</style>
