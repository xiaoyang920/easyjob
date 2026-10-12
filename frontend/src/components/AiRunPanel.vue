<template>
  <aside v-if="aiRunCount && route.path !== '/ai-chat'" class="ai-run-panel" :class="dockClass" aria-label="AI 任务状态">
    <button class="ai-run-toggle" :aria-expanded="open" @click="open = !open">
      <span class="ai-run-dot" :class="{ working: running }"></span>
      {{ running ? `${running} 个 AI 任务正在生成` : 'AI 对话有更新' }}<span>{{ aiRunCount }}</span>
    </button>
    <div v-if="open" class="ai-run-menu">
      <div class="ai-run-heading">对话动态<button aria-label="收起对话动态" @click="open = false">×</button></div>
      <p v-if="aiRunConnection === 'reconnecting'" role="status">暂时无法同步，正在重新连接…</p>
      <RouterLink v-for="item in aiRunItems" :key="item.runId" :to="{ path: '/ai-chat', query: { conversationId: item.conversationId } }" @click="open = false">
        <span>{{ item.title }}</span><small>{{ runLabel(item) }} ↗</small>
      </RouterLink>
    </div>
  </aside>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { aiRunItems, aiRunCount, aiRunConnection } from '@/utils/aiRuns'
import { runLabel } from '@/utils/runOverview'
const route = useRoute()
const open = ref(false)
const running = computed(() => aiRunItems.value.filter(item => item.status === 'running').length)
// 停靠位置由路由 meta 声明，见 router/index.ts 的 aiRunDock
const dockClass = computed(() => route.meta.aiRunDock ? `dock-${route.meta.aiRunDock}` : '')
</script>
<style scoped>
.ai-run-panel { position: fixed; right: 24px; bottom: 24px; z-index: 110; max-width: calc(100vw - 32px); }
.ai-run-toggle { display: flex; gap: 10px; align-items: center; border: 1px solid var(--ej-ink); background: var(--ej-surface); color: var(--ej-ink); border-radius: 24px; padding: 12px 16px; box-shadow: 3px 3px 0 #17171718; cursor: pointer; }
.ai-run-toggle > span:last-child { font-size: 12px; }
.ai-run-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--studio-lime); border: 1px solid var(--ej-ink); }
.ai-run-dot.working { animation: task-pulse 1.8s ease-in-out infinite; }
.ai-run-menu { position: absolute; right: 0; bottom: calc(100% + 12px); width: 320px; max-width: calc(100vw - 32px); max-height: 55vh; overflow: auto; border: 1px solid var(--ej-ink); border-radius: 18px; background: var(--ej-surface); box-shadow: 4px 4px 0 #17171718; padding: 16px; }
.ai-run-heading { display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
.ai-run-heading button { border: 0; background: none; font-size: 24px; cursor: pointer; }
.ai-run-menu a { display: flex; flex-direction: column; gap: 6px; padding: 14px 0; border-bottom: 1px solid #17171718; color: inherit; text-decoration: none; }
.ai-run-menu a > span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.ai-run-menu small, .ai-run-menu p { color: var(--ej-muted); font-size: 12px; }
/* 私信页底部是输入区：停到会话标题栏右侧，菜单改为向下展开 */
.ai-run-panel.dock-top { top: 104px; right: 40px; bottom: auto; }
.ai-run-panel.dock-top .ai-run-menu { top: calc(100% + 12px); bottom: auto; }
/* 文章页窄屏右下角是浮动按钮组（问 AI、聊天室、在线人数），浮窗排在按钮组上方并与其右对齐 */
@media (max-width: 1200px) { .ai-run-panel.dock-above-actions { right: 20px; bottom: 194px; } }
@media (max-width: 768px) { .ai-run-panel.dock-top { top: 86px; right: 24px; } }
@media (max-width: 480px) { .ai-run-panel.dock-above-actions { right: 15px; bottom: 172px; } }
@keyframes task-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .ai-run-dot.working { animation: none; } }
</style>
