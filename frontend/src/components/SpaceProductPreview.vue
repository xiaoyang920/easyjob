<template>
  <div class="product-art">
    <!-- A bundle shows each artwork it contains. -->
    <div v-if="artworks.length > 1" class="bundle-parts">
      <figure v-for="item in artworks" :key="item.artworkId">
        <img :src="artworkCover(item)" alt="">
        <figcaption>{{ slotLabel(item.slot) }}</figcaption>
      </figure>
    </div>
    <template v-else-if="!artwork || artwork.slot === avatarPendantSlot">
      <SpaceBanner />
      <div class="product-stage">
        <SpaceAvatar class="product-avatar" :src="avatar" :name="nickname" :pendant-url="pendantImage(artwork)" />
      </div>
    </template>
    <BubblePreview v-else-if="artwork.slot === chatBubbleSlot" :bubble="artwork" compact />
    <!-- Slots without a dedicated renderer show their images as delivered. -->
    <div v-else class="product-images">
      <img v-for="url in images" :key="url" :src="url" alt="">
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import SpaceBanner from './SpaceBanner.vue'
import SpaceAvatar from './SpaceAvatar.vue'
import BubblePreview from './BubblePreview.vue'
import { artworkCover, avatarPendantSlot, chatBubbleSlot, pendantImage, slotLabel, type SpaceArtwork } from '@/utils/spaceSkins'

const props = withDefaults(defineProps<{ artworks?: readonly SpaceArtwork[] }>(), { artworks: () => [] })
// Shoppers see the artwork on their own portrait.
const avatar = localStorage.getItem('avatar')
const nickname = localStorage.getItem('nickName')
const artwork = computed(() => props.artworks[0])
const images = computed(() => artwork.value
  ? [...Object.values(artwork.value.assets.images), ...artwork.value.assets.items.map(item => item.url)].slice(0, 8) : [])
</script>

<style scoped>
.product-art { overflow: hidden; border-bottom: 1px solid var(--ej-line); background: var(--ej-surface); }
.product-art :deep(.space-banner) { height: 96px; }
.product-stage { display: grid; place-items: center; padding-bottom: 26px; }
.product-avatar { width: 72px; margin-top: -40px; border: 2px solid var(--ej-surface); }
.product-images { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; min-height: 150px; padding: 16px; align-content: center; }
.product-images img { width: 56px; height: 56px; object-fit: contain; }
.bundle-parts { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; min-height: 150px; padding: 16px; align-content: center; }
.bundle-parts figure { display: grid; justify-items: center; gap: 4px; margin: 0; }
.bundle-parts img { width: 56px; height: 56px; object-fit: contain; }
.bundle-parts figcaption { color: var(--ej-muted); font-size: 12px; }
</style>
