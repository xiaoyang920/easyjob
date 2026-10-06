<template><template v-for="(part, index) in segments" :key="index"><mark v-if="part.highlighted">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></template>
<script setup lang="ts">
import { computed } from 'vue'
import { searchSegments } from '@/utils/searchHighlight'
const props = withDefaults(defineProps<{ text?: string; keyword?: string; esMarkers?: boolean }>(), { text: '', keyword: '', esMarkers: false })
const segments = computed(() => searchSegments(props.text, props.keyword, props.esMarkers))
</script>
<style scoped>mark { color: inherit; background: #d4ff77; border-radius: 3px; padding: 0 2px; }</style>
