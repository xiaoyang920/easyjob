<template>
  <el-popover :visible="open" placement="top-end" :width="280" popper-class="context-usage-popover" :show-arrow="false">
    <div class="context-details" data-testid="context-details">
      <strong>上下文窗口</strong>
      <template v-if="percent !== null && usage?.usedTokens != null">
        <div class="context-percent">{{ percent }}% 已用 <span>（剩余 {{ 100 - percent }}%）</span></div>
        <div :title="`${usage.usedTokens.toLocaleString()} / ${usage.limitTokens.toLocaleString()} Token`">已用 {{ formatContextTokens(usage.usedTokens) }}，共 {{ formatContextTokens(usage.limitTokens) }} Token</div>
        <small>最近一次主代理请求的估算值，包含系统提示、历史与工具资料；不含尚未发送的输入。</small>
      </template>
      <template v-else>
        <div>{{ failed ? '暂时无法获取用量' : '待计算' }}</div>
        <div v-if="usage">上下文上限 {{ formatContextTokens(usage.limitTokens) }} Token</div>
        <small>{{ failed ? '下次请求完成后会重新获取。' : '发送消息后显示最近一次请求的上下文用量。' }}</small>
      </template>
    </div>
    <template #reference>
      <button ref="button" type="button" class="context-meter" :class="{ 'context-meter-high': (percent ?? 0) >= 80 }"
        :aria-label="percent === null ? '上下文用量：待计算' : `上下文已用 ${percent}%`" :aria-expanded="open"
        @mouseenter="hovered = true" @mouseleave="hovered = false" @focus="focused = true" @blur="focused = false"
        @click="pinned ? close() : (pinned = true)" @keydown.esc.stop="close">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle class="context-track" cx="12" cy="12" r="8" />
          <circle v-if="percent !== null" class="context-fill" cx="12" cy="12" r="8" pathLength="100" :stroke-dasharray="`${percent} 100`" />
          <circle v-else cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
        </svg>
      </button>
    </template>
  </el-popover>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import request from '@/utils/request'
import { contextPercent, formatContextTokens, parseContextUsage, type ContextUsage } from '@/utils/contextUsage'

const props = defineProps<{ conversationId: string | null; liveUsage: ContextUsage | null; busy: boolean }>()
const fetched = ref<ContextUsage | null>(null)
const failed = ref(false)
const hovered = ref(false), focused = ref(false), pinned = ref(false)
const button = ref<HTMLButtonElement>()
const open = computed(() => hovered.value || focused.value || pinned.value)
const usage = computed(() => props.liveUsage || fetched.value)
const percent = computed(() => contextPercent(usage.value))
let version = 0
let controller: AbortController | undefined
function close() { hovered.value = focused.value = pinned.value = false }
function outside(event: PointerEvent) { if (!button.value?.contains(event.target as Node)) close() }
async function refresh() {
  const current = ++version
  controller?.abort()
  controller = new AbortController()
  if (!localStorage.getItem('token')) return
  try {
    const path = props.conversationId ? `/agent/conversations/${encodeURIComponent(props.conversationId)}/context-usage` : '/agent/context-usage'
    const response = await request.get(path, { signal: controller.signal })
    if (current !== version) return
    fetched.value = parseContextUsage(response.data)
    failed.value = !fetched.value
  } catch {
    if (current === version && !controller?.signal.aborted) failed.value = true
  }
}
watch(() => props.conversationId, () => { fetched.value = null; failed.value = false; close(); void refresh() }, { immediate: true })
watch(() => props.busy, (busy, wasBusy) => { if (!busy && wasBusy) void refresh() })
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => { ++version; controller?.abort(); document.removeEventListener('pointerdown', outside) })
</script>

<style scoped>
.context-meter { display: grid; place-items: center; flex: 0 0 30px; width: 30px; height: 34px; padding: 3px; border: 0; border-radius: 50%; background: transparent; color: #77786f; cursor: pointer; }
.context-meter:hover, .context-meter:focus-visible { background: #77786f15; color: #393a34; }
.context-meter:focus-visible { outline: 2px solid #8972d6; outline-offset: 2px; }
.context-meter-high { color: #a96921; }
.context-meter svg { width: 22px; height: 22px; transform: rotate(-90deg); }
.context-meter circle { stroke: currentColor; stroke-width: 2.5; fill: none; }
.context-meter .context-track { opacity: .22; }
.context-meter .context-fill { stroke-linecap: round; }
.context-details { color: #efefeb; font-size: 13px; line-height: 1.7; }
.context-details strong { display: block; color: #c3c3ba; font-size: 12px; font-weight: 500; margin-bottom: 4px; }
.context-percent { font-size: 15px; font-weight: 600; }
.context-percent span { font-weight: 400; }
.context-details small { display: block; color: #babbb3; font-size: 11px; line-height: 1.6; margin-top: 9px; }
:global(.el-popover.context-usage-popover) { background: #252623; border: 1px solid #41423a; border-radius: 13px; padding: 14px 16px; max-width: calc(100vw - 24px); box-sizing: border-box; box-shadow: 0 6px 22px #0002; }
</style>
