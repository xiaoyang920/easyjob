<template>
  <div class="article-rich-editor-host" :style="fullscreen ? { height: `${placeholderHeight}px` } : undefined">
    <Teleport to="body" :disabled="!fullscreen">
    <ElFocusTrap :trapped="fullscreen" :loop="fullscreen" :focus-trap-el="editorRoot" @release-requested="exitFullscreen">
    <div ref="editorRoot" class="article-rich-editor" :class="{ 'is-fullscreen': fullscreen }"
      :role="fullscreen ? 'dialog' : undefined" :aria-modal="fullscreen ? true : undefined"
      :aria-label="fullscreen ? '全屏编辑正文' : undefined" :tabindex="fullscreen ? -1 : undefined"
      :style="{ '--article-editor-height': height || '560px' }">
    <div v-if="fullscreen" class="fullscreen-bar">
      <span>全屏写作 <small>编辑正文</small></span>
      <button type="button" :disabled="leavingFullscreen" @click="exitFullscreen">退出全屏 <kbd>Esc</kbd></button>
    </div>
    <Toolbar class="toolbar" :editor="editorRef" :defaultConfig="toolbarConfig" mode="default" />
    <Editor class="editor" :style="{ height: fullscreen ? '0px' : 'var(--article-editor-height)' }" :model-value="modelValue" :defaultConfig="editorConfig" mode="default"
      @update:model-value="$emit('update:modelValue', $event)" @onCreated="handleCreated" />
    </div>
    </ElFocusTrap>
    </Teleport>
  </div>
</template>
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onUnmounted, ref, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import ElFocusTrap from 'element-plus/es/components/focus-trap/index.mjs'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import { Boot, DomEditor, type IDomEditor } from '@wangeditor/editor'
import request from '@/utils/request'
import { blockStyleMenuKey, registerArticleBlockStyle } from '@/utils/editorBlockStyle'
registerArticleBlockStyle()
defineProps<{ modelValue: string; height?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; ready: [html: string] }>()
const editorRef = shallowRef<IDomEditor>()
const editorRoot = ref<HTMLElement>()
const fullscreen = ref(false), leavingFullscreen = ref(false), placeholderHeight = ref(0)
let restoreBackground: (() => void) | undefined
let disposed = false
const toolbarConfig = { toolbarKeys: [
  blockStyleMenuKey, 'blockquote', '|', 'bold', 'underline', 'italic', 'through', 'color', 'bgColor', '|',
  'fontSize', 'lineHeight', '|', 'bulletedList', 'numberedList', 'todo', '|',
  'insertLink', 'uploadImage', 'insertTable', 'codeBlock', 'divider', '|', 'undo', 'redo', '|', 'fullScreen',
] }
const editorConfig = {
  placeholder: '开始创作你的文章…\n支持 Markdown 快捷输入：# 标题、``` 代码块、> 引用',
  hoverbarKeys: {
    ...Boot.editorConfig.hoverbarKeys,
    text: { menuKeys: [blockStyleMenuKey, 'insertLink', 'bulletedList', '|', 'bold', 'through', 'color', 'bgColor', 'clearStyle'] },
  },
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
  const enterFullscreen = editor.fullScreen.bind(editor)
  editor.fullScreen = () => {
    if (disposed || editor.isFullScreen) return
    placeholderHeight.value = editorRoot.value?.getBoundingClientRect().height || 0
    enterFullscreen()
  }
  editor.on('fullScreen', onFullscreen)
  editor.on('unFullScreen', onUnFullscreen)
  const html = editor.getHtml()
  emit('update:modelValue', html)
  emit('ready', html)
}
async function onFullscreen() {
  if (disposed) return
  fullscreen.value = true
  await nextTick()
  if (disposed || !fullscreen.value || restoreBackground) return
  // Keep the same editor instance/undo history, but move it above page/dialog
  // stacking contexts. The nested focus trap pauses an enclosing draft dialog.
  const root = editorRoot.value!
  const siblings = [...document.body.children].filter((node): node is HTMLElement => node instanceof HTMLElement && node !== root && !node.contains(root))
  const inert = siblings.map(node => [node, node.inert] as const)
  const overflow = [document.body, document.documentElement].map(node => ({ node, value: node.style.getPropertyValue('overflow'), priority: node.style.getPropertyPriority('overflow') }))
  inert.forEach(([node]) => { node.inert = true })
  overflow.forEach(({ node }) => node.style.setProperty('overflow', 'hidden'))
  restoreBackground = () => {
    inert.forEach(([node, value]) => { node.inert = value })
    overflow.forEach(({ node, value, priority }) => value ? node.style.setProperty('overflow', value, priority) : node.style.removeProperty('overflow'))
  }
}
function exitFullscreen(event?: Event) {
  event?.preventDefault()
  event?.stopPropagation()
  if (!fullscreen.value || leavingFullscreen.value || !editorRef.value || disposed) return
  leavingFullscreen.value = true
  editorRef.value.unFullScreen()
}
function onUnFullscreen() {
  if (disposed) return
  restoreBackground?.()
  restoreBackground = undefined
  fullscreen.value = false
  leavingFullscreen.value = false
  nextTick(() => editorRoot.value?.querySelector<HTMLButtonElement>('[data-menu-key="fullScreen"]')?.focus({ preventScroll: true }))
}
onBeforeUnmount(() => {
  disposed = true
  editorRef.value?.off('fullScreen', onFullscreen)
  editorRef.value?.off('unFullScreen', onUnFullscreen)
  restoreBackground?.()
  restoreBackground = undefined
})
// Toolbar is a child and may access the editor while it unmounts.
onUnmounted(() => {
  const editor = editorRef.value
  if (!editor) return
  // wangEditor 5.1 leaves a trailing throttled selection callback on close.
  // Cancel it before destroy removes the editor from its internal WeakMap.
  const textarea = DomEditor.getTextarea(editor) as unknown as { onDOMSelectionChange?: { cancel?: () => void } }
  textarea.onDOMSelectionChange?.cancel?.()
  editor.destroy()
  editorRef.value = undefined
})
</script>
<style scoped>
.article-rich-editor-host{min-width:0}
.article-rich-editor{--w-e-toolbar-bg-color:var(--ej-surface,#fffdf7);--w-e-textarea-bg-color:var(--ej-surface,#fffdf7);--w-e-toolbar-color:#333;--w-e-toolbar-active-color:#111;--w-e-toolbar-active-bg-color:#e8f6be;--w-e-toolbar-border-color:#e5e3dc;border:1px solid var(--ej-line,#dedbd2);border-radius:14px;background:var(--ej-surface,#fffdf7);min-width:0}
/* The editor's own .w-e-scroll owns scrolling. Clipping its wrapper hides
   upward-opening selection menus behind the toolbar. */
.toolbar{border-bottom:1px solid var(--ej-line,#dedbd2);border-radius:14px 14px 0 0}.editor{height:var(--article-editor-height);border-radius:0 0 14px 14px}
:deep(.w-e-text-container),:deep(.w-e-scroll){border-radius:0 0 14px 14px}:deep(.w-e-hover-bar){z-index:20}
:deep(.w-e-text-container){font-size:16px;line-height:1.8}:deep(.w-e-scroll){padding:8px 14px}:deep(img){max-width:100%;height:auto}:deep(pre){max-width:100%;overflow-x:auto}
.article-rich-editor.is-fullscreen{position:fixed;inset:0;z-index:4000;display:flex;flex-direction:column;width:100%;height:100dvh!important;max-height:none;max-width:none;margin:0;border:0;border-radius:0;box-sizing:border-box;isolation:isolate;background:var(--ej-surface,#fffdf7);color:var(--ej-ink,#171717)}
.is-fullscreen .toolbar{flex:none;border-radius:0}.is-fullscreen .editor{flex:1;min-height:0;border-radius:0}.is-fullscreen :deep(.w-e-text-container),.is-fullscreen :deep(.w-e-scroll){border-radius:0}.is-fullscreen :deep([data-slate-editor]){max-width:1200px;margin:0 auto;padding:0 clamp(14px,4vw,48px) 24px}
.fullscreen-bar{display:flex;flex:none;align-items:center;justify-content:space-between;gap:12px;padding:12px max(16px,env(safe-area-inset-right)) 12px max(16px,env(safe-area-inset-left));border-bottom:1px solid var(--ej-line,#dedbd2);background:var(--ej-surface,#fffdf7);font-size:14px;font-weight:700}.fullscreen-bar small{margin-left:10px;color:var(--ej-muted,#777);font-size:12px;font-weight:400}.fullscreen-bar button{display:flex;align-items:center;gap:10px;flex-shrink:0;padding:8px 16px;border:1px solid #171717;border-radius:999px;background:var(--studio-lime,#cbff46);color:#171717;font:inherit;font-size:13px;cursor:pointer}.fullscreen-bar button:focus-visible{outline:2px solid currentColor;outline-offset:3px}.fullscreen-bar kbd{font:inherit;font-size:11px;font-weight:400;opacity:.7}
@media(max-width:600px){:deep(.w-e-bar){gap:0}:deep(.w-e-bar-item){padding:2px}:deep(.w-e-scroll){padding:4px}}
</style>
