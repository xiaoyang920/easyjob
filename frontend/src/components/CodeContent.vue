<template><div ref="root" class="code-content" v-html="html" @click="expand"></div></template>
<script setup lang="ts">
import { onMounted, onUpdated, ref } from 'vue'
import { clickedCode, decorateCodeBlocks } from '@/utils/codeTools'
// HTML has already passed the display sanitizer in the caller.
defineProps<{ html: string }>()
const emit = defineEmits<{ expand: [code: {text:string;language:string}] }>()
const root = ref<HTMLElement>()
function decorate() { if (root.value) decorateCodeBlocks(root.value) }
function expand(event: MouseEvent) { const code = clickedCode(event, root.value); if (code) emit('expand', code) }
onMounted(decorate); onUpdated(decorate)
</script>
