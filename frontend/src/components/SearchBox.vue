<template>
  <form ref="root" class="search-box recent-search-control" role="search" @submit.prevent="submit()" @keydown.esc.stop.prevent="close" @focusout="onFocusOut">
    <input ref="input" v-model="query" type="search" placeholder="搜索文章、作者..." aria-label="搜索文章、作者" autocomplete="off" enterkeyhint="search" :maxlength="SEARCH_QUERY_LIMIT" :aria-expanded="opened" :aria-controls="panelId" @focus="show" @input="show" @keydown.enter="onEnter">
    <button class="search-btn" type="submit" aria-label="搜索"><Search /></button>
    <Transition name="search-history">
      <div v-if="opened" :id="panelId" class="search-history-panel" aria-label="最近搜索">
        <div class="search-history-heading"><span>最近搜索</span><button v-if="history.length" type="button" class="search-history-clear" @mousedown.prevent @click="clearAll">清空</button></div>
        <ul v-if="visibleHistory.length" class="search-history-list">
          <li v-for="term in visibleHistory" :key="term">
            <button type="button" class="search-history-pick" :aria-label="`再次搜索：${term}`" @mousedown.prevent @click="submit(term)"><Clock /><span>{{ term }}</span></button>
            <button type="button" class="search-history-delete" :aria-label="`删除搜索记录：${term}`" @mousedown.prevent @click="remove(term)"><Close /></button>
          </li>
        </ul>
        <p v-else class="search-history-empty">{{ history.length ? '没有匹配的搜索记录' : '暂无最近搜索' }}</p>
      </div>
    </Transition>
  </form>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId } from 'vue'
import { Clock, Close, Search } from '@element-plus/icons-vue'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'
import { SEARCH_QUERY_LIMIT, readSearchHistory, rememberSearch, deleteSearch, clearSearchHistory } from '@/utils/searchHistory'

const query = defineModel<string>({ default: '' })
const emit = defineEmits<{ search: [query: string] }>()
const root = ref<HTMLElement>()
const input = ref<HTMLInputElement>()
const opened = ref(false)
const history = ref<string[]>([])
const panelId = `search-history-${useId()}`
const visibleHistory = computed(() => {
  const text = query.value.trim().toLowerCase()
  return text ? history.value.filter(term => term.toLowerCase().includes(text)) : history.value
})
function show() { history.value = readSearchHistory(); opened.value = true }
function close() { opened.value = false }
function onFocusOut(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) close() }
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) close() }
function onEnter(event: KeyboardEvent) { if (event.isComposing || event.keyCode === 229) event.preventDefault() }
function submit(term = query.value) {
  const text = term.trim()
  if (!text) return
  query.value = text
  history.value = rememberSearch(text)
  close()
  input.value?.blur()
  emit('search', text)
}
function remove(term: string) { history.value = deleteSearch(term) }
function clearAll() { clearSearchHistory(); history.value = [] }
function accountChanged() { close(); history.value = readSearchHistory() }
function storageChanged(event: StorageEvent) {
  if (event.storageArea === localStorage) history.value = readSearchHistory()
}
onMounted(() => {
  document.addEventListener('pointerdown', outside)
  window.addEventListener('storage', storageChanged)
  eventBus.on(EVENT_AUTH_CHANGED, accountChanged)
  eventBus.on(EVENT_AUTH_EXPIRED, accountChanged)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', outside)
  window.removeEventListener('storage', storageChanged)
  eventBus.off(EVENT_AUTH_CHANGED, accountChanged)
  eventBus.off(EVENT_AUTH_EXPIRED, accountChanged)
})
</script>

<style>
#app .recent-search-control { position: relative; min-width: 0; }
#app .recent-search-control input { display: block; width: 100%; height: 40px; padding: 0 44px 0 18px; outline: none; }
#app .recent-search-control input::-webkit-search-cancel-button { appearance: none; }
#app .recent-search-control .search-btn { position: absolute; right: 5px; top: 50%; transform: translateY(-50%); display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 0; cursor: pointer; }
#app .recent-search-control .search-btn svg { width: 18px; height: 18px; }
#app .search-history-panel { position: absolute; z-index: 30; left: 0; top: calc(100% + 10px); width: 100%; min-width: 230px; padding: 14px 10px 10px; background: var(--ej-surface); border: 1px solid var(--ej-ink); border-radius: 16px; box-shadow: var(--ej-shadow-lift); overflow: hidden; }
#app .search-history-heading { display: flex; align-items: center; justify-content: space-between; padding: 0 8px 10px; font-size: 12px; font-weight: 650; color: var(--ej-muted); }
#app .search-history-clear { padding: 4px 6px; background: transparent; border: 0; border-radius: 6px; font: inherit; font-weight: 400; color: var(--ej-muted); cursor: pointer; }
#app .search-history-clear:hover { color: var(--ej-ink); background: var(--studio-lime-soft); }
#app .search-history-list { max-height: min(360px,calc(100dvh - 150px)); margin: 0; padding: 0; overflow-y: auto; list-style: none; }
#app .search-history-list li { display: flex; align-items: center; gap: 4px; border-radius: 10px; }
#app .search-history-list li:hover, #app .search-history-list li:focus-within { background: var(--studio-lime-soft); }
#app .search-history-pick { display: flex; flex: 1; min-width: 0; align-items: center; gap: 10px; padding: 10px 8px; background: transparent; border: 0; border-radius: 10px; color: var(--ej-ink); font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
#app .search-history-pick svg { flex-shrink: 0; width: 15px; height: 15px; color: var(--ej-muted); }
#app .search-history-pick span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#app .search-history-delete { display: grid; place-items: center; flex-shrink: 0; width: 30px; height: 30px; margin-right: 4px; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--ej-muted); cursor: pointer; }
#app .search-history-delete svg { width: 14px; height: 14px; }
#app .search-history-delete:hover { background: var(--ej-soft); color: var(--ej-ink); }
#app .search-history-empty { margin: 0; padding: 16px 8px; font-size: 12px; text-align: center; color: var(--ej-muted); }
#app .search-history-enter-active, #app .search-history-leave-active { transition: opacity 140ms, transform 180ms ease; }
#app .search-history-enter-from, #app .search-history-leave-to { opacity: 0; transform: translateY(-4px); }
@media(max-width: 768px) {
  #app .search-history-panel { position: fixed; top: 68px; left: 18px; right: 18px; width: auto; min-width: 0; }
  #app .recent-search-control input { height: 34px; padding: 0 32px 0 12px; font-size: 12px; }
  #app .recent-search-control .search-btn { right: 2px; width: 28px; height: 28px; }
  #app .recent-search-control .search-btn svg { width: 16px; height: 16px; }
}
</style>
