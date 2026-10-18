<template>
  <header class="navbar app-header" aria-label="站点导航">
    <HomeBrand />
    <span v-if="title" class="page-title app-header-title">{{ title }}</span>
    <button v-if="searchable" class="header-search-toggle" aria-label="搜索文章" :aria-expanded="mobileSearch" @click="mobileSearch = !mobileSearch"><Search /></button>
    <SearchBox v-if="searchable" v-model="keyword" :class="{ 'mobile-search-open':mobileSearch }" @search="search" />
    <div class="app-header-right">
      <div class="app-header-tools" :class="{ open: toolsOpen }">
        <button v-if="hasActions" class="header-tools-toggle" :aria-expanded="toolsOpen" aria-controls="page-header-actions" @click="toolsOpen = !toolsOpen">页面操作</button>
        <div id="page-header-actions" ref="actions" class="page-header-actions"></div>
      </div>
      <AppNavigation />
    </div>
  </header>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import HomeBrand from './HomeBrand.vue'
import SearchBox from './SearchBox.vue'
import AppNavigation from './AppNavigation.vue'
import { Search } from '@element-plus/icons-vue'
const route = useRoute(), router = useRouter()
const keyword = ref(''), toolsOpen = ref(false), actions = ref<HTMLElement>(), hasActions = ref(false)
const mobileSearch = ref(false)
const titles: Record<string,string> = { AiChat:'智能助手', Chat:'私信', Notifications:'消息通知', DraftBox:'草稿与审核', CreateArticle:'写文章', EditArticle:'编辑文章', EditProfile:'编辑资料', FollowersFollowing:'粉丝与关注', MemoryManagement:'长期记忆', AccountSecurity:'账号安全', PasswordReset:'找回密码', AdminConsole:'管理后台', ArticleDetail:'文章' }
const title = computed(() => titles[String(route.name)] || '')
const searchable = computed(() => ['Home','Search','UserSpace'].includes(String(route.name)))
function search(value: string) { void router.push({ path:'/search', query:{ keyword:value } }) }
watch(() => route.fullPath, () => { keyword.value = String(route.query.keyword || ''); toolsOpen.value = false; mobileSearch.value = false }, { immediate:true })
function outside(event: PointerEvent) { if (!(event.target as HTMLElement).closest('.app-header-tools')) toolsOpen.value = false }
let observer: MutationObserver | undefined
onMounted(() => {
  observer = new MutationObserver(() => { hasActions.value = !!actions.value?.children.length })
  if (actions.value) { observer.observe(actions.value, {childList:true}); hasActions.value = !!actions.value.children.length }
  document.addEventListener('pointerdown', outside)
})
onUnmounted(() => { observer?.disconnect(); document.removeEventListener('pointerdown', outside) })
</script>
<style>
#app .app-header { position:fixed; inset:0 0 auto; z-index:var(--ej-layer-header); display:flex; align-items:center; gap:18px; height:var(--ej-header-height); }
#app .app-header > .search-box { width:clamp(180px,28vw,440px); margin-inline:auto; }
#app .app-header-right { margin-left:auto; display:flex; align-items:center; gap:20px; }
#app .page-header-actions, #app .page-header-actions > .nav-right { display:flex; align-items:center; gap:8px; }
#app .page-header-actions:empty { display:none; }
#app .page-header-actions .nav-btn { padding:8px 16px; font:inherit; font-size:13px; cursor:pointer; }
#app .header-tools-toggle { display:none; }
#app .header-search-toggle { display:none; }
#app .app-header .app-header-title { margin-left:0; }
#app .account-security-page, #app .password-reset-page, #app .admin-console, #app .memory-page { padding-top:var(--ej-header-height); }
@media(max-width:900px) {
  #app .app-header { gap:10px; }
  #app .app-header-title { display:none; }
  #app .app-header-right { gap:10px; }
  #app .app-header-tools { position:relative; }
  #app .header-tools-toggle { display:block; font:inherit; font-size:12px; padding:8px 10px; border:1px solid var(--ej-line); border-radius:99px; background:var(--ej-surface); cursor:pointer; }
  #app .page-header-actions { display:none; position:absolute; top:calc(100% + 12px); right:0; padding:12px; border:1px solid var(--ej-ink); border-radius:14px; background:var(--ej-surface); box-shadow:var(--ej-shadow); white-space:nowrap; }
  #app .app-header-tools.open .page-header-actions { display:flex; }
}
@media(max-width:768px) {
  #app .app-header { height:var(--ej-header-height); padding-inline:18px; }
  #app .app-header > .search-box { width:auto; flex:1; }
  #app .account-security-page, #app .password-reset-page, #app .admin-console, #app .memory-page { padding-top:var(--ej-header-height); }
}
@media(max-width:600px) {
  #app .app-header > .search-box { display:none; }
  #app .header-search-toggle { display:grid; place-items:center; margin-left:auto; padding:8px; border:1px solid var(--ej-line); border-radius:50%; background:var(--ej-surface); }
  #app .header-search-toggle svg { width:18px; height:18px; }
  #app .app-header > .search-box.mobile-search-open { display:block; position:absolute; top:calc(100% + 8px); left:18px; right:18px; width:auto; background:var(--ej-surface); }
  #app .app-header-tools .header-tools-toggle { padding:8px; font-size:11px; }
}
</style>
