<template>
  <div class="article-rich-editor" :style="{ '--article-editor-height': height || '560px' }">
    <Toolbar class="toolbar" :editor="editorRef" :defaultConfig="toolbarConfig" mode="default" />
    <Editor class="editor" :style="{ height: 'var(--article-editor-height)' }" :model-value="modelValue" :defaultConfig="editorConfig" mode="default"
      @update:model-value="$emit('update:modelValue', $event)" @onCreated="handleCreated" />
  </div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onUnmounted, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import type { IDomEditor } from '@wangeditor/editor'
import request from '@/utils/request'
defineProps<{ modelValue: string; height?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; ready: [html: string] }>()
const editorRef = shallowRef<IDomEditor>()
let disposed = false
const toolbarConfig = { toolbarKeys: [
  'headerSelect', 'blockquote', '|', 'bold', 'underline', 'italic', 'through', 'color', 'bgColor', '|',
  'fontSize', 'lineHeight', '|', 'bulletedList', 'numberedList', 'todo', '|',
  'insertLink', 'uploadImage', 'insertTable', 'codeBlock', 'divider', '|', 'undo', 'redo', '|', 'fullScreen',
] }
const editorConfig = {
  placeholder: '开始创作你的文章…\n支持 Markdown 快捷输入：# 标题、``` 代码块、> 引用',
  MENU_CONF: {
    uploadImage: {
      maxFileSize: 15 * 1024 * 1024, allowedFileTypes: ['image/*'],
      async customUpload(file: File, insertFn: (url: string, alt: string, href: string) => void) {
        const form = new FormData()
        form.append('file', file)
        try {
          const res = await request.post('/file/upload-article-image', form, { headers: { 'Content-Type': 'multipart/form-data' } })
          if (res.code !== 200 || !res.data?.url) throw new Error(res.message || '图片上传失败')
          if (!disposed) insertFn(res.data.url, '', res.data.url)
        } catch (error) { ElMessage.error(error instanceof Error ? error.message : '图片上传失败') }
      },
    },
    codeSelectLang: { codeLangs: [
      { text: 'Java', value: 'java' }, { text: 'JavaScript', value: 'javascript' },
      { text: 'TypeScript', value: 'typescript' }, { text: 'Python', value: 'python' },
      { text: 'Go', value: 'go' }, { text: 'C/C++', value: 'cpp' }, { text: 'SQL', value: 'sql' },
      { text: 'HTML', value: 'html' }, { text: 'CSS', value: 'css' }, { text: 'Shell', value: 'bash' },
      { text: 'JSON', value: 'json' }, { text: 'XML', value: 'xml' },
    ] },
  },
}
function handleCreated(editor: IDomEditor) {
  if (disposed) { editor.destroy(); return }
  editorRef.value = editor
  const html = editor.getHtml()
  emit('update:modelValue', html)
  emit('ready', html)
}
onBeforeUnmount(() => { disposed = true })
// Toolbar is a child and may access the editor while it unmounts.
onUnmounted(() => { editorRef.value?.destroy(); editorRef.value = undefined })
</script>
<style scoped>
.article-rich-editor{--w-e-toolbar-bg-color:var(--ej-surface,#fffdf7);--w-e-textarea-bg-color:var(--ej-surface,#fffdf7);--w-e-toolbar-color:#333;--w-e-toolbar-active-color:#111;--w-e-toolbar-active-bg-color:#e8f6be;--w-e-toolbar-border-color:#e5e3dc;border:1px solid var(--ej-line,#dedbd2);border-radius:14px;background:var(--ej-surface,#fffdf7);overflow:hidden;min-width:0}
.toolbar{border-bottom:1px solid var(--ej-line,#dedbd2)}.editor{height:var(--article-editor-height);overflow-y:auto}
:deep(.w-e-text-container){font-size:16px;line-height:1.8}:deep(.w-e-scroll){padding:8px 14px}:deep(img){max-width:100%;height:auto}:deep(pre){max-width:100%;overflow-x:auto}
@media(max-width:600px){:deep(.w-e-bar){gap:0}:deep(.w-e-bar-item){padding:2px}:deep(.w-e-scroll){padding:4px}}
</style>
