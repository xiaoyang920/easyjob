<template>
  <RouterLink to="/" class="logo home-brand" aria-label="EasyJob 首页" title="返回首页" :aria-current="route.path === '/' ? 'page' : undefined">
    <span class="logo-text">EasyJob</span>
    <span class="logo-home">首页</span>
  </RouterLink>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<style scoped>
#app .home-brand { flex-shrink: 0; gap: 9px; text-decoration: none; border-radius: 8px; }
#app .home-brand:hover { transform: none; }
#app .home-brand .logo-home { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; padding: 4px 8px; border: 1px solid var(--ej-line); border-radius: 99px; background: var(--ej-surface); color: var(--ej-ink); font-size: 11px; font-weight: 600; letter-spacing: 0; line-height: 1.3; transition: background 180ms, border-color 180ms; }
#app .home-brand:hover .logo-home { background: var(--studio-lime); border-color: var(--ej-ink); }
#app .home-brand:focus-visible { outline: 2px solid var(--ej-ink); outline-offset: 5px; }
@media (max-width: 480px) {
  #app .home-brand { gap: 7px; }
  #app .home-brand .logo-text { display: none; }
  #app .home-brand .logo-home { padding: 4px 7px; }
}
@media (prefers-reduced-motion: reduce) { #app .home-brand .logo-home { transition: none; } }
</style>
