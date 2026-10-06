<template>
  <div class="easyjob-shell">
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
import AiRunPanel from './components/AiRunPanel.vue'
import { onMounted, onUnmounted } from 'vue'
import { startAiRunMonitor, stopAiRunMonitor } from './utils/aiRuns'
onMounted(startAiRunMonitor)
onUnmounted(stopAiRunMonitor)
</script>

<style>
/* 全局样式会在这里，但主要样式在各个组件中 */
</style>
