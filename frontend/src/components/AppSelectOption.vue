<script lang="ts">
import { defineComponent } from 'vue'

/** Native option-shaped usage keeps string/number values and translated labels intact. */
export default defineComponent({
  name:'AppSelectOption',
  inheritAttrs:false,
  props:{ value:{type:[String,Number,Boolean],required:true}, disabled:Boolean },
  // AppSelect reads declarations and renders real ElOptions, including while closed.
  render:()=>null,
})
</script>
