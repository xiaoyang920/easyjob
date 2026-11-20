<template>
  <section aria-label="挂件佩戴预览">
    <div class="preview-options">
      <label>背景<select v-model="mode" aria-label="背景"><option value="day">日间</option><option value="night">夜间</option></select></label>
      <label>头像尺寸<select v-model.number="diameter" aria-label="头像尺寸"><option :value="120">桌面 120px</option>
        <option :value="80">手机 80px</option><option :value="70">小屏 70px</option></select></label>
    </div>
    <div class="pendant-preview" :data-pendant-preview="mode">
      <SpaceBanner />
      <div class="sample-profile" :class="{ compact: diameter < 120 }">
        <SpaceAvatar :pendant-url="url" :src="avatar" :name="nickname" :style="{ width: diameter + 'px' }" alt="预览头像" />
        <strong>{{ nickname }}</strong>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import SpaceAvatar from './SpaceAvatar.vue'
import SpaceBanner from './SpaceBanner.vue'

defineProps<{ url?: string }>()
const mode = ref('day')
const diameter = ref(120)
const avatar = localStorage.getItem('avatar')
const nickname = localStorage.getItem('nickName') || '空间昵称'
</script>

<style scoped>
.preview-options { display: flex; gap: 12px; margin-bottom: 10px; }
.preview-options label { display: grid; gap: 5px; color: var(--ej-muted); font-size: 13px; }
.preview-options select { padding: 7px 9px; border: 1px solid var(--ej-line); border-radius: 8px; color: var(--ej-ink); background: var(--ej-surface); }
.pendant-preview { min-height: 228px; overflow: hidden; border: 1px solid var(--ej-line);
  background: var(--ej-surface); border-radius: 16px; }
.sample-profile { position: relative; display: flex; align-items: center; flex-wrap: wrap; gap: 44px; padding: 0 44px 36px; color: var(--ej-ink); }
.sample-profile .space-avatar { margin-top: -50px; }
.sample-profile.compact { flex-direction: column; gap: 30px; }
.sample-profile.compact .space-avatar { margin-top: -32px; }
</style>
