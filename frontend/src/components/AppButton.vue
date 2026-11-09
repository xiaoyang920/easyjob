<template>
  <button :type="type" class="ej-button" :class="[`ej-button--${variant}`, { 'ej-button--small': size === 'small' }]" :disabled="disabled"><slot /></button>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  type?: 'button' | 'submit' | 'reset'
  variant?: 'secondary' | 'primary' | 'quiet' | 'danger'
  size?: 'default' | 'small'
  disabled?: boolean
}>(), { type: 'button', variant: 'secondary', size: 'default', disabled: false })
</script>
