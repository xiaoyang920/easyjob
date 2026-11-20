<template>
  <div class="comment-image-input">
    <input ref="picker" type="file" multiple accept="image/jpeg,image/png,image/gif,image/webp" aria-label="选择评论图片" hidden :disabled="disabled || busy" @change="selected" />
    <div class="picture-controls">
      <button v-if="modelValue.length < maxImages || busy" type="button" class="picture-add" :disabled="disabled || busy" @click="choose">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/></svg>
        {{ busy ? `上传中 ${progress}%` : '添加图片' }}
      </button>
      <small v-if="!busy">可粘贴图片 · {{ modelValue.length }}/{{ maxImages }} 张，每张最大 5 MB</small>
    </div>
    <div v-if="modelValue.length" class="picture-list">
      <div v-for="(image, index) in modelValue" :key="image" class="picture-ready">
        <CommentImage :src="image" />
        <button type="button" class="picture-remove" :aria-label="modelValue.length === 1 ? '移除评论图片' : `移除第 ${index + 1} 张评论图片`"
          :disabled="disabled || busy" @click="emit('update:modelValue', modelValue.filter((_, i) => i !== index))">×</button>
      </div>
    </div>
    <p v-if="error" class="picture-error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { uploadFile } from '@/utils/upload'
import { errorMessage } from '@/utils/feedback'
import CommentImage from './CommentImage.vue'

const props = defineProps<{ modelValue: string[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [images: string[]]; busy: [value: boolean]; login: [] }>()
const maxImages = 9
const picker = ref<HTMLInputElement>(), busy = ref(false), progress = ref(0), error = ref('')
let disposed = false
function loggedIn() { if (!localStorage.getItem('token')) { emit('login'); return false }; return true }
function choose() { if (loggedIn()) picker.value?.click() }
async function upload(files: File[]) {
  if (!files.length || props.disabled || busy.value || !loggedIn()) return
  error.value = ''
  const owner = localStorage.getItem('userId')
  const images = [...props.modelValue]
  busy.value = true; progress.value = 0; emit('busy', true)
  try {
    for (const file of files) {
      if (disposed || owner !== localStorage.getItem('userId')) return
      if (images.length >= maxImages) { error.value = '每条评论最多添加 9 张图片'; break }
      if (!['image/jpeg','image/png','image/gif','image/webp'].includes(file.type)) { error.value = '请选择 JPG、PNG、GIF 或 WebP 图片'; continue }
      if (file.size > 5 * 1024 * 1024) { error.value = '图片不能超过 5MB'; continue }
      progress.value = 0
      try {
        const result = await uploadFile({ url: '/file/upload-comment-image', file, onProgress: value => { if (!disposed) progress.value = value } })
        if (disposed || owner !== localStorage.getItem('userId')) return
        if (result.code !== 200 || !result.data?.url) throw new Error(result.message || '图片上传失败，请重新选择')
        images.push(result.data.url)
        emit('update:modelValue', [...images])
      } catch (err) {
        if (!disposed) error.value = errorMessage(err, '图片上传失败，已上传的图片和文字已保留')
      }
    }
  }
  finally { if (!disposed) { busy.value = false; emit('busy', false) } }
}
function selected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  void upload(files)
}
function paste(event: ClipboardEvent) {
  const clipboard = event.clipboardData
  if (!clipboard) return
  const files = Array.from(clipboard.files).filter(file => file.type.startsWith('image/'))
  if (!files.length) {
    for (const item of Array.from(clipboard.items)) {
      const file = item.kind === 'file' && item.type.startsWith('image/') ? item.getAsFile() : null
      if (file) files.push(file)
    }
  }
  if (!files.length) return
  if (!clipboard.getData('text/plain')) event.preventDefault()
  void upload(files)
}
onBeforeUnmount(() => {
  disposed = true
  if (busy.value) emit('busy', false)
})
defineExpose({ paste })
</script>

<style scoped>
.comment-image-input { min-width:0; margin-top:10px; }
.picture-controls { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.picture-add { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--ej-line,var(--ej-line)); border-radius:20px; padding:7px 11px; background:var(--ej-paper,var(--ej-canvas)); color:var(--ej-ink,var(--ej-ink)); font:inherit; font-size:12px; cursor:pointer; }
.picture-add:hover:not(:disabled) { border-color:var(--ej-ink,var(--ej-ink)); background:var(--ej-lime,#c6ff40); color: var(--ej-on-color); }
.picture-add:disabled,.picture-remove:disabled { opacity:.5; cursor:default; }
.picture-controls small { color:var(--ej-muted,var(--ej-body)); font-size:11px; }
.picture-ready { display:inline-block; max-width:100%; position:relative; padding-right:12px; }
.picture-list { display:flex; flex-wrap:wrap; gap:8px; }
.picture-ready :deep(.comment-picture img) { max-height:100px; }
.picture-remove { position:absolute; right:0; top:4px; width:25px; height:25px; border:1px solid var(--ej-ink,var(--ej-ink)); border-radius:50%; background:var(--ej-paper,var(--ej-canvas)); color:var(--ej-ink,var(--ej-ink)); cursor:pointer; font:inherit; }
.picture-error { color:#ad382c; font-size:12px; margin:8px 0 0; }
</style>
