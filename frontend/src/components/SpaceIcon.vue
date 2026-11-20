<template>
  <img v-if="url && url !== failed" :key="url" class="space-icon" :class="{ 'is-active': active }" :src="url" alt="" aria-hidden="true" @error="failed = url">
  <slot v-else />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { SpaceArtwork } from '@/utils/spaceSkins'
import { siteIconPack } from '@/utils/siteIconPack'

const props = defineProps<{ pack?: SpaceArtwork, name: string, site?: boolean, active?: boolean }>()
const url = computed(() => (props.site ? siteIconPack.value : props.pack)?.assets?.images?.[props.name])
const failed = ref<string>()
watch(url, () => { failed.value = undefined })
</script>

<style scoped>
.space-icon { display: inline-block; width: var(--space-icon-size, 1.25em); height: var(--space-icon-size, 1.25em); object-fit: contain; vertical-align: -0.25em; flex: none; }
.space-icon.is-active { border-radius: 2px; outline: 1px solid currentColor; outline-offset: 2px; }
</style>
