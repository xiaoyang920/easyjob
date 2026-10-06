<template>
  <div class="content-state" :class="`content-state--${kind}`" :role="kind === 'error' ? 'alert' : 'status'" :aria-busy="kind === 'loading'">
    <span v-if="kind === 'loading'" class="content-state-spinner" aria-hidden="true"></span>
    <p class="content-state-title">{{ title }}</p>
    <p v-if="description" class="content-state-description">{{ description }}</p>
    <button v-if="kind === 'error'" type="button" class="content-state-retry" @click="$emit('retry')">重新加载</button>
    <slot />
  </div>
</template>
<script setup lang="ts">
defineProps<{ kind: 'loading' | 'error' | 'empty'; title: string; description?: string }>()
defineEmits<{ retry: [] }>()
</script>
<style>
#app .content-state { display:flex; flex-direction:column; align-items:center; gap:12px; padding:56px 24px; background:var(--ej-surface); border:1px solid var(--ej-line); border-radius:18px; text-align:center; }
#app .content-state-title { margin:0; color:var(--ej-ink); font-size:16px; font-weight:600; }
#app .content-state-description { margin:0; color:var(--ej-muted); font-size:14px; max-width:38em; overflow-wrap:anywhere; }
#app .content-state-retry { border:1px solid var(--ej-ink); border-radius:999px; padding:8px 20px; background:var(--ej-lime, #c6ff40); cursor:pointer; color:var(--ej-ink); }
#app .content-state-spinner { width:22px; height:22px; border:2px solid var(--ej-line); border-top-color:var(--ej-ink); border-radius:50%; animation:content-state-spin .8s linear infinite; }
@keyframes content-state-spin { to { transform:rotate(360deg); } }
</style>
