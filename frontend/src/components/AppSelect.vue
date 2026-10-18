<template>
  <ElSelect ref="control" v-bind="$attrs" class="ej-select" :model-value="modelValue"
    :disabled="disabled || fieldsetDisabled" :placeholder="placeholder || '请选择'"
    :aria-label="accessibleLabel" :aria-required="required || undefined"
    :empty-values="[null, undefined]" no-data-text="暂无可选项" no-match-text="没有匹配选项" :popper-class="['ej-select-menu', popperClass].filter(Boolean).join(' ')"
    @update:model-value="emit('update:modelValue', $event)" @change="emit('change', $event)"
    @focus="emit('focus', $event)" @blur="emit('blur', $event)">
    <ElOption v-for="option in options()" :key="String(option.value)" :value="option.value" :label="option.label" :disabled="option.disabled" />
  </ElSelect>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useAttrs, useSlots, type VNode } from 'vue'
import { ElSelect, ElOption } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
defineOptions({ inheritAttrs:false })
const props = defineProps<{modelValue?:string|number|boolean|null; disabled?:boolean; required?:boolean; placeholder?:string; popperClass?:string; modelModifiers?:{number?:boolean;trim?:boolean}}>()
const emit = defineEmits<{'update:modelValue':[value:string|number|boolean];change:[value:string|number|boolean];focus:[event:FocusEvent];blur:[event:FocusEvent]}>()
const attrs = useAttrs(), control = ref<InstanceType<typeof ElSelect>>(), label = ref(''), fieldsetDisabled = ref(false)
const slots = useSlots()
type Option = {value:string|number|boolean;label:string;disabled:boolean}
function text(nodes:VNode[]):string { return nodes.map(node=>typeof node.children==='string'?node.children:Array.isArray(node.children)?text(node.children as VNode[]):'').join('') }
function options(nodes:VNode[]=slots.default?.() || []):Option[] {
  return nodes.flatMap(node=>{
    if (Array.isArray(node.children)) return options(node.children as VNode[])
    if ((node.type as {name?:string})?.name !== 'AppSelectOption') return []
    const children = node.children as {default?:()=>VNode[]} | null
    return [{value:node.props?.value,label:text(children?.default?.() || []).replace(/\s+/g,' ').trim(),disabled:node.props?.disabled === '' || (!!node.props?.disabled && node.props.disabled!=='false')}]
  })
}
const accessibleLabel = computed(() => String(attrs['aria-label'] || label.value || '') || undefined)
let observer: MutationObserver | undefined
onMounted(() => {
  const root = control.value?.$el as HTMLElement | undefined
  if (props.required) root?.querySelector('[role=combobox]')?.setAttribute('aria-required','true')
  const fieldset = root?.closest('fieldset')
  if (fieldset) {
    const update = () => { fieldsetDisabled.value = fieldset.disabled }
    update(); observer = new MutationObserver(update); observer.observe(fieldset,{attributes:true,attributeFilter:['disabled']})
  }
  // Preserve the accessible names of the existing implicit and for/id labels.
  const parent = root?.closest('label') || (attrs.id ? document.querySelector(`label[for="${CSS.escape(String(attrs.id))}"]`) : null)
  if (parent) {
    const copy = parent.cloneNode(true) as HTMLElement
    copy.querySelectorAll('.ej-select').forEach(node => node.remove())
    label.value = copy.textContent?.replace(/\s+/g,' ').trim() || ''
  }
})
onUnmounted(() => observer?.disconnect())
defineExpose({
  focus(options?:FocusOptions) { (control.value?.$el as HTMLElement | undefined)?.querySelector<HTMLInputElement>('[role=combobox]')?.focus(options) },
  scrollIntoView(options?:ScrollIntoViewOptions) { (control.value?.$el as HTMLElement | undefined)?.scrollIntoView(options) },
})
</script>
