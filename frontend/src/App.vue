<template>
  <div class="easyjob-shell">
    <AppHeader />
    <router-view v-slot="{ Component, route }">
      <Transition name="page" mode="out-in">
        <div :key="route.path" class="page-frame">
          <component :is="Component" />
        </div>
      </Transition>
    </router-view>
    <AiRunPanel />
  </div>
</template>

<script setup lang="ts">
import './styles/theme.css'
import './styles/night.css'
import './styles/space-skins.css'
import AiRunPanel from './components/AiRunPanel.vue'
import AppHeader from './components/AppHeader.vue'
import { onMounted, onUnmounted } from 'vue'
import { startAiRunMonitor, stopAiRunMonitor } from './utils/aiRuns'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from './utils/eventBus'
import { syncSiteIconPack } from './utils/siteIconPack'

function syncIconsOnStorage(event: StorageEvent) {
  if (event.storageArea === localStorage && (!event.key || event.key === 'token' || event.key === 'userId')) {
    void syncSiteIconPack()
  }
}

onMounted(startAiRunMonitor)
onUnmounted(stopAiRunMonitor)
onMounted(() => {
  void syncSiteIconPack()
  eventBus.on(EVENT_AUTH_CHANGED, syncSiteIconPack)
  eventBus.on(EVENT_AUTH_EXPIRED, syncSiteIconPack)
  window.addEventListener('focus', syncSiteIconPack)
  window.addEventListener('storage', syncIconsOnStorage)
})
onUnmounted(() => {
  eventBus.off(EVENT_AUTH_CHANGED, syncSiteIconPack)
  eventBus.off(EVENT_AUTH_EXPIRED, syncSiteIconPack)
  window.removeEventListener('focus', syncSiteIconPack)
  window.removeEventListener('storage', syncIconsOnStorage)
})
</script>

<style>
/* 全局样式会在这里，但主要样式在各个组件中 */
</style>
