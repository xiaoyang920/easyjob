<template>
  <span class="space-avatar" :class="{ 'with-pendant': artworkUrl }" :style="artworkUrl ? { borderWidth: '0px' } : undefined">
    <img class="portrait" :src="avatarUrl(src, name)" :alt="alt" @error="onAvatarError($event, name)">
    <img v-if="artworkUrl" class="pendant-art" :src="artworkUrl" alt="" draggable="false" :style="pendantStyle">
  </span>
</template>

<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { avatarUrl, onAvatarError } from '@/utils/avatar'
import { pendantAperture } from '@/utils/pendantAperture'
import { getPendant, requestPendant } from '@/utils/pendantDirectory'
import { pendantGeometry } from '@/utils/spaceSkins'

const props = withDefaults(defineProps<{ src?: string | null, name?: string | null, alt?: string, pendantUrl?: string, userId?: string | number | null }>(), { alt: '' })
const artworkUrl = computed(() => props.pendantUrl ?? getPendant(props.userId))
watch(() => props.userId, requestPendant, { immediate: true })
const aperture = shallowRef<Awaited<ReturnType<typeof pendantAperture>>>()
const pendantStyle = computed(() => {
  const fit = aperture.value
  return {
    width: 100 / (fit?.fraction ?? pendantGeometry.avatarFraction) + '%',
    transform: fit ? 'translate(' + (-100 * fit.x) + '%, ' + (-100 * fit.y) + '%)' : undefined,
  }
})
watch(artworkUrl, (url, _, onCleanup) => {
  aperture.value = undefined
  if (!url) return
  let current = true
  onCleanup(() => { current = false })
  void pendantAperture(url).then(result => { if (current) aperture.value = result })
}, { immediate: true })
</script>

<style scoped>
.space-avatar {
  position: relative; display: inline-block; width: 84px; aspect-ratio: 1; border-radius: 50%;
  background: var(--ej-surface); vertical-align: top; flex-shrink: 0;
}
.portrait { display: block; width: 100%; height: 100%; border-radius: inherit; object-fit: cover; }
.pendant-art {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  height: auto; max-width: none; aspect-ratio: 1; pointer-events: none; user-select: none; z-index: 1;
}
</style>
