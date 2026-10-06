<template>
  <section class="reading-progress" v-if="progress">
    <div class="reading-heading"><strong>阅读等级 L{{ progress.level }}</strong><span>累计 {{ readingDuration(progress.totalSeconds) }}</span></div>
    <div class="reading-meter" role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"><i :style="{ width: `${percent}%` }"></i></div>
    <p>{{ progress.nextLevel === null ? '已达到当前最高等级，阅读时间继续累计' : `距离 L${progress.nextLevel} 还需有效阅读 ${readingDuration(progress.secondsToNext)}` }}</p>
    <small v-if="status">{{ status }}</small>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { readingDuration, type ReadingProgress } from '@/utils/readingGrowth'
const props = defineProps<{ progress?: ReadingProgress; status?: string }>()
const percent = computed(() => {
  const p = props.progress
  if (!p || p.nextLevel === null) return 100
  const floor = p.rules.find(r => r.level === p.level)?.minSeconds || 0
  const ceiling = p.rules.find(r => r.level === p.nextLevel)?.minSeconds || 0
  return Math.max(0, Math.min(100, Math.round((p.totalSeconds - floor) / Math.max(1, ceiling - floor) * 100)))
})
</script>
<style scoped>
.reading-progress { padding: 18px; background: #fffdf6; border: 1px solid #242420; border-radius: 18px; }
.reading-heading { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; font-size: 13px; }
.reading-heading span, p, small { color: #777b6d; }
.reading-meter { height: 6px; margin: 14px 0 10px; border-radius: 8px; background: #e7e5db; overflow: hidden; }
.reading-meter i { display: block; height: 100%; background: #bdff39; transition: width .35s ease; }
p { margin: 0; font-size: 12px; line-height: 1.6; } small { display: block; margin-top: 8px; font-size: 11px; }
@media (prefers-reduced-motion: reduce) { .reading-meter i { transition: none; } }
</style>
