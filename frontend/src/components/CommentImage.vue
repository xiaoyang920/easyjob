<template>
  <button v-if="src" type="button" class="comment-picture" aria-label="查看评论图片" @click="preview = true">
    <img :src="src" alt="评论配图" loading="lazy" />
    <span>查看大图</span>
  </button>
  <ElImageViewer v-if="preview && src" :url-list="[src]" :z-index="10000" teleported hide-on-click-modal @close="preview = false" />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElImageViewer } from 'element-plus'
// Explicit component imports bypass the resolver's automatic style imports.
import 'element-plus/theme-chalk/el-image-viewer.css'
import 'element-plus/theme-chalk/el-icon.css'
defineProps<{ src?: string }>()
const preview = ref(false)
</script>

<style scoped>
.comment-picture { display:block; position:relative; max-width:100%; margin:12px 0; padding:0; overflow:hidden; border:1px solid var(--ej-line,#d3d0c7); border-radius:12px; background:var(--ej-bg,#f2efe6); cursor:zoom-in; }
.comment-picture img { display:block; width:auto; max-width:100%; max-height:200px; object-fit:contain; }
.comment-picture span { position:absolute; bottom:6px; right:6px; padding:3px 8px; border-radius:20px; background:rgba(0,0,0,.65); color:white; font-size:11px; }
.comment-picture:focus-visible { outline:2px solid var(--ej-ink,#141414); outline-offset:3px; }
</style>
