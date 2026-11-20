<template>
  <div v-if="images.length" :class="images.length > 1 ? 'comment-gallery' : undefined">
    <button v-for="(image, index) in images" :key="image" type="button" class="comment-picture"
      :aria-label="images.length === 1 ? '查看评论图片' : `查看第 ${index + 1} 张评论图片`" @click="previewIndex = index">
      <img :src="image" alt="评论配图" loading="lazy" />
      <span v-if="images.length === 1">查看大图</span>
    </button>
  </div>
  <ElImageViewer v-if="previewIndex !== null && images[previewIndex]" :url-list="images"
    :initial-index="previewIndex" :z-index="10000" teleported hide-on-click-modal @close="previewIndex = null" />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElImageViewer } from 'element-plus'
// Explicit component imports bypass the resolver's automatic style imports.
import 'element-plus/theme-chalk/el-image-viewer.css'
import 'element-plus/theme-chalk/el-icon.css'
const props = defineProps<{ src?: string | null; sources?: string[] | null }>()
const images = computed(() => props.sources?.length ? props.sources : props.src ? [props.src] : [])
const previewIndex = ref<number | null>(null)
</script>

<style scoped>
.comment-picture { display:block; position:relative; max-width:100%; margin:12px 0; padding:0; overflow:hidden; border:1px solid var(--ej-line,var(--ej-line)); border-radius:12px; background:var(--ej-bg,var(--ej-canvas)); cursor:zoom-in; }
.comment-picture img { display:block; width:auto; max-width:100%; max-height:200px; object-fit:contain; }
.comment-picture span { position:absolute; bottom:6px; right:6px; padding:3px 8px; border-radius:20px; background:rgba(0,0,0,.65); color:white; font-size:11px; }
.comment-picture:focus-visible { outline:2px solid var(--ej-ink,var(--ej-ink)); outline-offset:3px; }
.comment-gallery { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; max-width:360px; margin:12px 0; }
.comment-gallery .comment-picture { margin:0; aspect-ratio:1; }
.comment-gallery .comment-picture img { width:100%; height:100%; object-fit:cover; }
</style>
