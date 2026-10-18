<template>
  <button v-if="quote" type="button" class="comment-quote-preview" aria-label="查看评论引用的原文" @click="emit('locate', quote)">
    <span>引用原文</span><q>{{ quote.exact }}</q><span class="quote-link">查看位置 ↗</span>
  </button>
</template>
<script setup lang="ts">
import type { CommentQuote } from '@/utils/commentAnchors'
defineProps<{ quote?: CommentQuote }>()
const emit = defineEmits<{ locate: [quote: CommentQuote] }>()
</script>
<style scoped>
.comment-quote-preview { display:flex; flex-direction:column; align-items:flex-start; gap:5px; width:100%; margin:8px 0; border:0; border-left:3px solid var(--studio-lime,#baff32); border-radius:0 8px 8px 0; background:var(--ej-bg,#f2efe6); color:var(--ej-muted); padding:10px 12px; text-align:left; font:inherit; font-size:12px; cursor:pointer; }
q { color:var(--ej-ink); white-space:pre-wrap; overflow-wrap:anywhere; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:3; overflow:hidden; }
q::before,q::after { content:none; }
.quote-link { font-size:11px; }
.comment-quote-preview:hover .quote-link { color:var(--ej-ink); text-decoration:underline; }
</style>
