<template>
  <div class="conversation-item" :class="{ active, 'is-pinned': pinned, 'menu-open': menuOpen }">
    <button class="conversation-open" :aria-pressed="active" :title="title" @click="emit('select')">
      <span class="conv-icon" aria-hidden="true"><component :is="conversation.originArticleId ? Document : ChatDotRound" /></span>
      <span class="conv-info">
        <span class="conv-title">{{ title }}</span>
        <span v-if="conversation.originArticleId" class="conv-article-title" :title="conversation.originArticleTitle || '原文章已不可用'">来源：{{ conversation.originArticleTitle || '原文章已不可用' }}</span>
        <span class="conv-time">
          <span v-if="pinned" class="conv-pinned-badge" :title="`固定在${category}顶部`">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3h6l-1 6 4 4v2H6v-2l4-4-1-6Z"/><path d="M12 15v6"/></svg>
            已置顶
          </span>
          <span v-if="status" class="conv-run-status" role="status">{{ status }}</span>
          <span v-else-if="time">{{ time }}</span>
        </span>
      </span>
    </button>
    <el-dropdown trigger="click" placement="bottom-end" popper-class="ai-conversation-menu" :disabled="updating" @command="onCommand" @visible-change="menuOpen = $event">
      <button class="conv-menu-trigger" :aria-label="`对话「${title}」的更多操作`" title="更多操作" aria-haspopup="menu" :aria-expanded="menuOpen" :disabled="updating" @click.stop>
        <component :is="updating ? Loading : MoreFilled" :class="{ 'is-spinning': updating }" aria-hidden="true" /><span>更多</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="pin" :disabled="updating">
            <svg class="conversation-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3h6l-1 6 4 4v2H6v-2l4-4-1-6Z"/><path d="M12 15v6"/></svg>
            <span class="conversation-action-copy"><strong>{{ pinned ? '取消置顶' : '置顶对话' }}</strong><small>{{ pinned ? '恢复按最近更新排序' : `固定在${category}顶部` }}</small></span>
          </el-dropdown-item>
          <el-dropdown-item command="rename" :disabled="updating">
            <EditPen class="conversation-action-icon" /><span class="conversation-action-copy"><strong>重命名对话</strong><small>修改标题，方便以后找到</small></span>
          </el-dropdown-item>
          <el-dropdown-item command="delete" divided :disabled="busy || updating" class="conversation-action-delete">
            <Delete class="conversation-action-icon" /><span class="conversation-action-copy"><strong>删除对话</strong><small>{{ busy ? '请先停止生成，再删除' : '删除前会再次确认' }}</small></span>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChatDotRound, Document, MoreFilled, EditPen, Delete, Loading } from '@element-plus/icons-vue'

const props = defineProps<{
  conversation: { title?: string; isPinned?: boolean | number | string; originArticleId?: string; originArticleTitle?: string }
  active: boolean
  time: string
  status?: string
  busy?: boolean
  updating?: boolean
}>()
const emit = defineEmits<{ select: []; pin: []; rename: []; delete: [] }>()
const menuOpen = ref(false)
const title = computed(() => props.conversation.title || '新对话')
const pinned = computed(() => !!Number(props.conversation.isPinned))
const category = computed(() => props.conversation.originArticleId ? '文章问答' : '普通聊天')
function onCommand(command: string) {
  if (props.updating) return
  if (command === 'pin') emit('pin')
  else if (command === 'rename') emit('rename')
  else if (command === 'delete' && !props.busy) emit('delete')
}
</script>

<style scoped>
.conversation-open { display: flex; align-items: flex-start; gap: 10px; flex: 1; min-width: 0; padding: 13px 0 13px 12px; border: 0; background: transparent; color: var(--ej-ink); text-align: left; cursor: pointer; border-radius: 12px; font: inherit; }
.conv-icon { display: flex; width: 20px; height: 22px; align-items: center; justify-content: center; flex-shrink: 0; }
.conv-icon svg { width: 17px; height: 17px; }
.conv-info { display: flex; flex: 1; flex-direction: column; min-width: 0; gap: 5px; }
.conv-title { display: block; min-width: 0; line-height: 1.5; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv-article-title { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: var(--ej-muted); }
.conv-time { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; min-height: 16px; line-height: 1.4; color: var(--ej-muted); }
.conv-pinned-badge { display: inline-flex; align-items: center; gap: 3px; padding: 2px 5px; border-radius: 5px; background: var(--studio-lime-soft); color: #445b1d; font-size: 10px; font-weight: 600; white-space: nowrap; }
.conv-pinned-badge svg { width: 11px; height: 11px; }
.conv-run-status { display: inline-flex; align-items: center; gap: 5px; color: var(--ej-ink); }
.conv-run-status::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: var(--studio-lime); border: 1px solid var(--ej-ink); }
.el-dropdown { align-self: center; flex-shrink: 0; margin: 0 7px 0 4px; }
.conv-menu-trigger { display: inline-flex; align-items: center; gap: 3px; min-height: 32px; padding: 5px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--ej-muted); font-size: 11px; cursor: pointer; transition: color 160ms, background 160ms; }
.conv-menu-trigger svg { width: 14px; height: 14px; }
.conv-menu-trigger:hover, .menu-open .conv-menu-trigger { color: var(--ej-ink); background: var(--ej-soft); }
.conv-menu-trigger:disabled { opacity: .5; cursor: wait; }
.is-spinning { animation: conversation-spin 1s linear infinite; }
@media (pointer: coarse) { .conv-menu-trigger { min-height: 44px; } }
@keyframes conversation-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .is-spinning { animation: none; } }
:global(.ai-conversation-menu.el-popper) { min-width: 228px; border: 1px solid var(--ej-line); border-radius: 14px; background: var(--ej-surface); box-shadow: 0 8px 28px #11110f18; }
:global(.ai-conversation-menu .el-dropdown-menu) { padding: 6px; background: transparent; border-radius: 14px; }
:global(.ai-conversation-menu .el-dropdown-menu__item) { display: flex; align-items: center; gap: 11px; padding: 10px; border-radius: 9px; color: var(--ej-ink); line-height: 1.4; }
:global(.ai-conversation-menu .el-dropdown-menu__item:not(.is-disabled):focus) { background: var(--ej-soft); color: var(--ej-ink); }
:global(.ai-conversation-menu .conversation-action-icon) { flex-shrink: 0; width: 18px; height: 18px; margin-right: 0; }
:global(.ai-conversation-menu .conversation-action-copy) { display: flex; flex-direction: column; gap: 4px; }
:global(.ai-conversation-menu .conversation-action-copy strong) { font-size: 13px; font-weight: 600; }
:global(.ai-conversation-menu .conversation-action-copy small) { font-size: 11px; color: var(--ej-muted); }
:global(.ai-conversation-menu .conversation-action-delete:not(.is-disabled)) { color: #a43b2c; }
:global(.ai-conversation-menu .conversation-action-delete:not(.is-disabled):focus) { background: #ffede7; color: #a43b2c; }
:global(.ai-conversation-menu .el-dropdown-menu__item.is-disabled) { opacity: .6; }
</style>
