<template>
  <section class="agent-activity" :class="displayStatus">
    <button class="activity-header" @click="expanded = !isExpanded" :aria-expanded="isExpanded">
      <span class="status-indicator" :class="displayStatus">{{ displayStatus === 'warning' || displayStatus === 'error' ? '!' : displayStatus === 'complete' ? '✓' : '' }}</span>
      <span class="activity-summary" aria-live="polite">{{ summary }}</span>
      <span v-if="elapsed !== null" class="activity-duration">{{ elapsed }} 秒</span>
      <svg :class="{ open: isExpanded }" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m8 10 4 4 4-4"/></svg>
    </button>
    <div class="activity-reveal" :class="{ open: isExpanded }" :inert="!isExpanded" :aria-hidden="!isExpanded">
      <div class="activity-body">
        <TransitionGroup name="activity-row" tag="div" class="activity-list">
          <div v-for="entry in timeline" :key="`${entry.kind}:${entry.id}`">
            <div v-if="entry.kind === 'commentary'" class="activity-commentary">{{ entry.text }}</div>
            <div v-else-if="entry.kind === 'result'" class="activity-result">
              <div class="result-label">{{ entry.label ? `${entry.label} · 结果` : '任务结果' }}</div>
              <div>{{ entry.text }}</div>
            </div>
            <div v-else-if="entry.kind === 'plan'" class="task-plan">
              <div class="section-label">任务计划</div>
              <div v-for="task in entry.tasks" :key="task.id" class="plan-item">
                <span class="item-mark" :class="task.status">{{ task.status === 'done' ? '✓' : task.status === 'error' ? '!' : '·' }}</span>
                <div class="plan-content">
                  <div :id="`${planId}-${task.id}`" class="plan-text">{{ expandedPlans.has(task.id) ? task.label : task.preview }}</div>
                  <button v-if="task.hasMore" type="button" class="plan-toggle"
                    :aria-expanded="expandedPlans.has(task.id)" :aria-controls="`${planId}-${task.id}`"
                    @click="togglePlan(task.id)">{{ expandedPlans.has(task.id) ? '收起' : '展开完整计划' }}</button>
                </div>
                <span class="task-type">{{ roleLabels[task.role] || '处理' }}</span>
              </div>
            </div>
            <div v-else-if="entry.kind === 'activity' && entry.item" class="activity-item">
              <span class="item-mark" :class="entry.item.status">{{ entry.item.status === 'done' ? '✓' : entry.item.status === 'error' ? '!' : entry.item.status === 'paused' ? 'Ⅱ' : '·' }}</span>
              <div class="item-content">
                <div class="item-title">{{ entry.item.label }} <span v-if="entry.item.actor === 'subagent'" class="agent-badge">子任务</span></div>
                <div v-if="entry.item.detail" class="item-detail">{{ entry.item.detail }}</div>
              </div>
              <span v-if="entry.item.finishedAt && entry.item.startedAt" class="item-duration">{{ ((entry.item.finishedAt - entry.item.startedAt) / 1000).toFixed(1) }}s</span>
            </div>
          </div>
        </TransitionGroup>
        <div v-if="!timeline.length" class="waiting-copy">
          {{ state.status === 'working' ? '正在准备处理请求…' : '该回复未保留处理明细。' }}
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId } from 'vue'
import type { AgentStreamState } from '@/utils/agentStream'
import { deliveryReviewWarning } from '@/utils/agentStream'

const props = defineProps<{ state: AgentStreamState }>()
const expanded = ref<boolean | null>(null)
const planId = `agent-plan-${useId()}`
const expandedPlans = ref(new Set<string>())
const timeline = computed(() => {
  const activities = new Map(props.state.activities.map(item => [item.id, item]))
  const tasks = new Map(props.state.plan.map(task => {
    const chars = Array.from(task.label)
    return [task.id, { ...task, hasMore: chars.length > 160,
      preview: chars.length > 160 ? chars.slice(0, 160).join('') + '…' : task.label }] as const
  }))
  const entries = props.state.timeline.length ? props.state.timeline
    : props.state.activities.map(item => ({ kind: 'activity' as const, id: item.id }))
  return entries.map(entry => {
    if (entry.kind === 'activity') return { ...entry, item: activities.get(entry.id) }
    if (entry.kind === 'plan') return { ...entry, tasks: entry.taskIds.flatMap(id => {
      const task = tasks.get(id)
      return task ? [task] : []
    }) }
    if (entry.kind === 'result') return { ...entry,
      label: entry.taskId ? activities.get(`${entry.taskId}/task`)?.label : undefined }
    return entry
  })
})
function togglePlan(id: string) {
  const next = new Set(expandedPlans.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedPlans.value = next
}
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval>
onMounted(() => { timer = setInterval(() => { now.value = Date.now() }, 1000) })
onUnmounted(() => clearInterval(timer))
const reviewWarning = computed(() => deliveryReviewWarning(props.state))
const displayStatus = computed(() => reviewWarning.value ? 'warning' : props.state.status)
const isExpanded = computed(() => expanded.value ?? ['working', 'awaiting', 'error', 'warning'].includes(displayStatus.value))
const elapsed = computed(() => {
  const start = props.state.startedAt
  const end = props.state.finishedAt ?? (props.state.status === 'working' ? now.value : undefined)
  return start === undefined || end === undefined || end < start ? null : Math.round((end - start) / 1000)
})
const roleLabels: Record<string, string> = { search: '检索', tool: '工具', memory: '记忆', analysis: '分析', writing: '写作' }
const summary = computed(() => {
  const state = props.state
  if (reviewWarning.value) return reviewWarning.value
  if (state.status === 'complete') return state.activities.length ? `处理完成 · ${state.activities.length} 项活动` : '处理完成'
  if (state.status === 'awaiting') return '草稿已准备好，等待你确认'
  if (state.status === 'cancelled') return '已停止处理'
  if (state.status === 'error') return '处理未完成'
  const active = state.activities.filter(item => item.status === 'active')
  const tasks = active.filter(item => item.actor === 'subagent' && item.id.endsWith('/task'))
  if (tasks.length > 1) return `${tasks.length} 个子任务正在并行处理`
  return active.at(-1)?.label || '正在理解请求'
})
</script>

<style scoped>
.agent-activity { margin: 0 0 14px; width: min(100%, 660px); color: var(--ej-body); font-size: 12px; }
.activity-header { display: flex; align-items: center; gap: 9px; width: 100%; padding: 10px 0; border: 0; background: transparent; color: inherit; cursor: pointer; text-align: left; }
.activity-summary { flex: 1; font-weight: 500; }
.activity-duration, .item-duration { font-size: 11px; color: var(--ej-muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.activity-header svg { transition: transform .2s; }
.activity-header svg.open { transform: rotate(180deg); }
.status-indicator { width: 14px; height: 14px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 11px; }
.status-indicator.working { border: 2px solid var(--ej-line); border-top-color: var(--ej-line); animation: activity-spin .9s linear infinite; }
.status-indicator.complete { color: color-mix(in srgb, #47846c var(--ej-shade), var(--ej-ink)); background: var(--ej-canvas); }
.status-indicator.error { color: #bd6a53; background: var(--ej-canvas); }
.status-indicator.warning { color: color-mix(in srgb, #947226 var(--ej-shade), var(--ej-ink)); background: color-mix(in srgb, #fff4d8 var(--ej-tint), var(--ej-surface)); }
.status-indicator.awaiting { background: #d6b775; width: 7px; height: 7px; margin: 3px; color: var(--ej-on-color); }
.status-indicator.cancelled { background: #a5a9af; width: 7px; height: 7px; margin: 3px; }
.activity-reveal { display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows 350ms cubic-bezier(.22, 1, .36, 1), opacity 200ms ease; }
.activity-reveal.open { grid-template-rows: 1fr; opacity: 1; }
.activity-body { min-height: 0; overflow: hidden; margin-left: 6px; padding: 0 0 0 17px; border-left: 1px solid var(--ej-line); }
.activity-commentary { color: var(--ej-body); line-height: 1.75; margin: 0 0 12px; }
.activity-result { color: var(--ej-body); line-height: 1.65; margin: 0 0 10px 23px; overflow-wrap: anywhere; }
.result-label { color: var(--ej-body); font-size: 11px; }
.task-plan { margin: 0 0 13px; padding: 8px 0; background: transparent; border: 0; border-radius: 0; }
.section-label { color: var(--ej-muted); font-size: 11px; margin-bottom: 8px; }
.plan-item { display: flex; align-items: flex-start; gap: 8px; padding: 4px 0; line-height: 1.6; }
.plan-content { flex: 1; min-width: 0; }
.plan-text { overflow-wrap: anywhere; white-space: pre-wrap; }
.plan-toggle { display: block; margin-top: 3px; padding: 3px 0; border: 0; background: transparent; color: var(--ej-body); font: inherit; font-size: 11px; cursor: pointer; }
.plan-toggle:hover { text-decoration: underline; }
.plan-toggle:focus-visible { outline: 2px solid var(--ej-line); outline-offset: 3px; border-radius: 2px; }
.plan-item > .task-type { flex-shrink: 0; }
.task-type, .agent-badge { border: 0; border-radius: 3px; background: var(--ej-canvas); padding: 0 5px; font-size: 10px; color: var(--ej-body); white-space: nowrap; font-weight: 400; }
.activity-item { display: flex; align-items: flex-start; gap: 9px; padding: 6px 0; }
.item-mark { display: inline-flex; width: 13px; flex-shrink: 0; justify-content: center; color: var(--ej-muted); line-height: 20px; }
.item-mark.active { color: color-mix(in srgb, #566577 var(--ej-shade), var(--ej-ink)); animation: activity-pulse 1.2s ease-in-out infinite; }
.item-mark.done { color: #6b947d; }
.item-mark.error { color: #bb6a54; }
.item-mark.paused { color: #b39a65; }
.item-content { flex: 1; min-width: 0; }
.item-title { line-height: 20px; }
.agent-badge { margin-left: 5px; }
.item-detail { color: var(--ej-muted); font-size: 12px; line-height: 1.6; margin-top: 2px; }
.waiting-copy { color: var(--ej-muted); padding: 4px 0; }
.activity-row-enter-active, .activity-row-leave-active, .activity-row-move { transition: opacity 220ms ease, transform 300ms cubic-bezier(.22, 1, .36, 1); }
.activity-row-enter-from, .activity-row-leave-to { opacity: 0; transform: translateY(5px); }
@keyframes activity-spin { to { transform: rotate(360deg); } }
@keyframes activity-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .status-indicator.working, .item-mark.active { animation: none; } .activity-reveal, .activity-row-enter-active, .activity-row-leave-active, .activity-row-move { transition: none; } }
</style>
