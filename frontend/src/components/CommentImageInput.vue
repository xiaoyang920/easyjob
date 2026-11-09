<template>
  <div class="comment-image-input">
    <input ref="picker" type="file" accept="image/jpeg,image/png,image/gif,image/webp" aria-label="选择评论图片" hidden :disabled="disabled || busy" @change="selected" />
    <div class="picture-controls">
      <button v-if="!modelValue" type="button" class="picture-add" :disabled="disabled || busy" @click="choose">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/></svg>
        {{ busy ? `上传中 ${progress}%` : '添加图片' }}
      </button>
      <small v-if="!modelValue && !busy">可粘贴图片 · 每条 1 张，最大 5MB</small>
    </div>
    <div v-if="modelValue" class="picture-ready">
      <CommentImage :src="modelValue" />
      <button type="button" class="picture-remove" aria-label="移除评论图片" :disabled="disabled" @click="emit('update:modelValue', '')">×</button>
    </div>
    <p v-if="error" class="picture-error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { uploadFile } from '@/utils/upload'
import { errorMessage } from '@/utils/feedback'
import CommentImage from './CommentImage.vue'

const props = defineProps<{ modelValue: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [url: string]; busy: [value: boolean]; login: [] }>()
const picker = ref<HTMLInputElement>(), busy = ref(false), progress = ref(0), error = ref('')
let disposed = false
function loggedIn() { if (!localStorage.getItem('token')) { emit('login'); return false }; return true }
function choose() { if (loggedIn()) picker.value?.click() }
async function upload(file: File) {
  if (props.disabled || busy.value || !loggedIn()) return
  error.value = ''
  if (props.modelValue) { error.value = '每条评论可配一张图片，请先移除已有图片'; return }
  if (!['image/jpeg','image/png','image/gif','image/webp'].includes(file.type)) { error.value = '请选择 JPG、PNG、GIF 或 WebP 图片'; return }
  if (file.size > 5 * 1024 * 1024) { error.value = '图片不能超过 5MB'; return }
  const owner = localStorage.getItem('userId')
  busy.value = true; progress.value = 0; emit('busy', true)
  try {
    const result = await uploadFile({ url: '/file/upload-comment-image', file, onProgress: value => { if (!disposed) progress.value = value } })
    if (disposed || owner !== localStorage.getItem('userId')) return
    if (result.code !== 200 || !result.data?.url) throw new Error(result.message || '图片上传失败，请重新选择')
    emit('update:modelValue', result.data.url)
  } catch (err) { if (!disposed) error.value = errorMessage(err, '图片上传失败，文字已保留，请重新选择') }
  finally { if (!disposed) { busy.value = false; emit('busy', false) } }
}
function selected(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''
  if (file) void upload(file)
}
function paste(event: ClipboardEvent) {
  const file = Array.from(event.clipboardData?.items || []).find(item => item.kind === 'file' && item.type.startsWith('image/'))?.getAsFile()
  if (file) { event.preventDefault(); void upload(file) }
}
onUnmounted(() => { disposed = true })
defineExpose({ paste })
</script>

<style scoped>
.comment-image-input { min-width:0; margin-top:10px; }
.picture-controls { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.picture-add { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--ej-line,#d3d0c7); border-radius:20px; padding:7px 11px; background:var(--ej-paper,#fffdf6); color:var(--ej-ink,#141414); font:inherit; font-size:12px; cursor:pointer; }
.picture-add:hover:not(:disabled) { border-color:var(--ej-ink,#141414); background:var(--ej-lime,#c6ff40); }
.picture-add:disabled,.picture-remove:disabled { opacity:.5; cursor:default; }
.picture-controls small { color:var(--ej-muted,#79776f); font-size:11px; }
.picture-ready { display:inline-block; max-width:100%; position:relative; padding-right:12px; }
.picture-ready :deep(.comment-picture img) { max-height:100px; }
.picture-remove { position:absolute; right:0; top:4px; width:25px; height:25px; border:1px solid var(--ej-ink,#141414); border-radius:50%; background:var(--ej-paper,#fffdf6); color:var(--ej-ink,#141414); cursor:pointer; font:inherit; }
.picture-error { color:#ad382c; font-size:12px; margin:8px 0 0; }
</style>
