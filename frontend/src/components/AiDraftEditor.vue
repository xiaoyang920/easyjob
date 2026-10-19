<template>
  <section class="ai-draft-editor">
    <div class="editor-toolbar">
      <span>{{ modelValue ? '有手动修改 · 确认后保存' : '可修改标题、摘要与正文' }}</span>
      <button class="edit-trigger" :disabled="disabled" @click="startEditing">直接编辑</button>
    </div>
    <div class="editor-preview"><slot :content="draft.content" :format="draft.content_format" /></div>
    <ElDialog v-model="editing" class="ai-draft-dialog ej-dialog" title="编辑草稿" width="min(1200px, 96vw)"
      align-center destroy-on-close :close-on-click-modal="false" :close-on-press-escape="false" append-to-body>
      <p class="modal-intro">与写文章使用相同的编辑器。应用修改后回到预览，确认后再保存到草稿箱。</p>
      <div class="editor-fields">
        <label>标题<input v-model="working.title" aria-label="草稿标题" maxlength="100" placeholder="请输入文章标题" /></label>
        <label>摘要 <small>{{ Array.from(working.summary).length }}/500</small>
          <textarea v-model="working.summary" aria-label="草稿摘要" rows="2" placeholder="简要介绍文章内容" /></label>
      </div>
      <ArticleRichEditor v-if="editing" v-model="editorHtml" height="var(--draft-editor-height, max(240px, calc(100dvh - 405px)))" @ready="editorReady" />
      <template #footer>
        <span class="editor-note">手动编辑不会调用 AI</span>
        <button class="modal-cancel" @click="editing=false">取消修改</button>
        <button class="modal-apply" :disabled="disabled" @click="applyChanges">应用修改</button>
      </template>
    </ElDialog>
  </section>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElDialog, ElMessage } from 'element-plus'
import { marked } from 'marked'
import ArticleRichEditor from './ArticleRichEditor.vue'
import { safeHtml } from '@/utils/safeHtml'
import { draftBodyHtml, type SourceLink } from '@/utils/citationLinks'
import { draftEditError, type DraftEdit } from '@/utils/draftEdit'
const props = defineProps<{ modelValue?: DraftEdit; initial: DraftEdit; disabled: boolean; citations?: SourceLink[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: DraftEdit] }>()
const editing = ref(false)
const draft = computed(() => props.modelValue || props.initial)
const working = ref<DraftEdit>({ title: '', summary: '', content: '' })
const editorHtml = ref('')
let initialEditorHtml = ''
function startEditing() {
  working.value = { ...draft.value }
  editorHtml.value = draftBodyHtml(safeHtml(draft.value.content_format === 'html' ? draft.value.content : marked.parse(draft.value.content, { breaks: true, gfm: true }) as string), props.citations)
  initialEditorHtml = editorHtml.value
  editing.value = true
}
function editorReady(html: string) {
  // Normalizing imported HTML must not rewrite unchanged Markdown.
  initialEditorHtml = html
}
function applyChanges() {
  const bodyChanged = editorHtml.value !== initialEditorHtml
  const updated: DraftEdit = { ...working.value, ...(bodyChanged ? { content: safeHtml(editorHtml.value), content_format: 'html' as const } : {}) }
  if (bodyChanged && !new DOMParser().parseFromString(updated.content, 'text/html').body.textContent?.trim()
      && !/<(?:img|table|hr)\b/i.test(updated.content)) { ElMessage.warning('正文不能为空'); return }
  const error = draftEditError(updated)
  if (error) { ElMessage.warning(error); return }
  if (JSON.stringify(updated) !== JSON.stringify(draft.value)) emit('update:modelValue', updated)
  editing.value = false
}
</script>
<style scoped>
.editor-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px;border-bottom:1px solid var(--ej-line,#e5e3dc)}.editor-toolbar>span{font-size:12px;color:var(--ej-muted,#777)}
.edit-trigger,.modal-apply,.modal-cancel{padding:9px 18px;border:1px solid #171717;border-radius:999px;background:transparent;color:#171717;font:inherit;font-size:13px;cursor:pointer}.edit-trigger,.modal-apply{background:var(--studio-lime,#cbff46)}button:disabled{opacity:.5;cursor:default}button:focus-visible{outline:2px solid currentColor;outline-offset:3px}
.modal-intro{margin:0 0 16px;color:var(--ej-muted,#777);font-size:13px;line-height:1.7}.editor-fields{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:16px}.editor-fields label{display:block;font-size:12px;font-weight:600}.editor-fields small{float:right;color:#777;font-weight:400}.editor-fields input,.editor-fields textarea{box-sizing:border-box;display:block;width:100%;margin-top:8px;padding:10px 12px;border:1px solid var(--ej-line,#dedbd2);border-radius:10px;background:var(--ej-surface,#fffdf7);color:#171717;font:inherit;font-size:15px;line-height:1.6;resize:vertical}.editor-fields input{font-weight:600}.editor-fields :is(input,textarea):focus{outline:2px solid #cbff46;outline-offset:1px}.editor-note{margin-right:auto;color:#777;font-size:12px}
:global(.ai-draft-dialog){padding:24px;border:1px solid #171717;border-radius:20px;background:var(--ej-surface,#fffdf7);max-height:96dvh;overflow:auto}:global(.ai-draft-dialog .el-dialog__header){padding-bottom:12px}:global(.ai-draft-dialog .el-dialog__title){font-size:22px;font-weight:700;color:#171717}:global(.ai-draft-dialog .el-dialog__footer){display:flex;align-items:center;gap:10px;padding-top:18px}
@media(max-width:600px){.editor-toolbar{padding:12px}.editor-fields{grid-template-columns:1fr;gap:10px;margin-bottom:10px}.modal-intro{font-size:12px;margin-bottom:10px}.editor-note{display:none}:global(.ai-draft-dialog){padding:16px;--draft-editor-height:240px}:global(.ai-draft-dialog .el-dialog__footer){justify-content:flex-end}.editor-fields textarea{resize:none}}
</style>
