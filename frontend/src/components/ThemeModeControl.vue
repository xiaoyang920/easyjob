<template>
  <details ref="menu" class="theme-mode" @focusout="onFocusOut" @keydown.esc.stop="close(true)">
    <summary ref="toggle" :aria-label="'显示模式 · ' + labels[mode]" :title="'显示模式 · ' + labels[mode]">
      <Moon v-if="dark" /><Sunny v-else />
    </summary>
    <div class="theme-mode-options" role="group" aria-label="显示模式">
      <button v-for="choice in choices" :key="choice" type="button" :aria-pressed="mode === choice" @click="select(choice)">
        {{ labels[choice] }}
      </button>
    </div>
  </details>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { Moon, Sunny } from '@element-plus/icons-vue'

const KEY = 'easyjob-display-mode'
const choices = ['light', 'dark', 'system'] as const
type DisplayMode = typeof choices[number]
const labels: Record<DisplayMode, string> = { light: '日间', dark: '夜间', system: '跟随系统' }
const root = document.documentElement
const system = window.matchMedia('(prefers-color-scheme: dark)')
const mode = ref<DisplayMode>(parseMode(root.dataset.displayMode))
const dark = ref(root.classList.contains('dark'))
const menu = ref<HTMLDetailsElement>()
const toggle = ref<HTMLElement>()

function parseMode(value?: string | null): DisplayMode {
  return value === 'light' || value === 'dark' ? value : 'system'
}

function apply() {
  dark.value = mode.value === 'dark' || (mode.value === 'system' && system.matches)
  root.classList.toggle('dark', dark.value)
  root.style.colorScheme = dark.value ? 'dark' : 'light'
  root.dataset.displayMode = mode.value
}

function select(choice: DisplayMode) {
  mode.value = choice
  try { localStorage.setItem(KEY, choice) } catch { /* The current tab can still change mode. */ }
  apply()
  close(true)
}

function close(restoreFocus: boolean) {
  if (menu.value) menu.value.open = false
  if (restoreFocus) toggle.value?.focus()
}

function onFocusOut(event: FocusEvent) {
  if (!menu.value?.contains(event.relatedTarget as Node | null)) close(false)
}

function sync(event: StorageEvent) {
  if (event.key !== KEY && event.key !== null) return
  mode.value = parseMode(event.newValue)
  apply()
}

onMounted(() => {
  apply()
  system.addEventListener('change', apply)
  window.addEventListener('storage', sync)
})

onUnmounted(() => {
  system.removeEventListener('change', apply)
  window.removeEventListener('storage', sync)
})
</script>

<style scoped>
.theme-mode { position: relative; flex: 0 0 auto; color: var(--ej-ink); }
.theme-mode[open] { z-index: 3; }
.theme-mode summary {
  list-style: none; width: 36px; height: 36px; display: grid; place-items: center; cursor: pointer;
  border: 1px solid var(--ej-line); border-radius: 50%; background: var(--ej-surface);
}
.theme-mode summary::-webkit-details-marker { display: none; }
.theme-mode summary svg { width: 18px; height: 18px; }
.theme-mode summary:hover { background: var(--studio-lime); color: var(--ej-on-color); }
.theme-mode-options {
  position: absolute; top: calc(100% + 10px); right: 0; z-index: 1; display: grid; gap: 4px; min-width: 108px;
  padding: 6px; border: 1px solid var(--ej-ink); border-radius: 12px; background: var(--ej-surface); box-shadow: var(--ej-shadow);
}
.theme-mode-options button {
  text-align: left; padding: 6px 10px; border: 0; border-radius: 7px; background: transparent; color: var(--ej-ink);
  font-size: 13px; white-space: nowrap; cursor: pointer;
}
.theme-mode-options button:hover { background: var(--ej-soft); }
.theme-mode-options button[aria-pressed=true] { background: var(--studio-lime); color: var(--ej-on-color); }
@media (max-width: 600px) { .theme-mode summary { width: 32px; height: 32px; } }
</style>
