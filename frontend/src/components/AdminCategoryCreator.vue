<template>
  <el-dialog v-model="visible" title="新增文章分类" width="min(540px, 94vw)" align-center :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" :before-close="close" append-to-body class="ej-dialog">
    <ContentState v-if="loading" kind="loading" title="正在加载分类" />
    <ContentState v-else-if="loadError" kind="error" title="暂时无法加载分类" :description="loadError" @retry="load" />
    <form v-else id="category-create-form" class="category-form" @submit.prevent="save">
      <fieldset :disabled="saving">
        <label>分类名称<input v-model="name" maxlength="50" required autocomplete="off" placeholder="例如：后端开发" /></label>
        <label>所属分类<AppSelect v-model="parent"><AppSelectOption value="0">一级分类</AppSelectOption><AppSelectOption v-for="row in roots" :key="row.categoryId" :value="row.categoryId">{{ row.categoryName }} / 二级分类</AppSelectOption></AppSelect></label>
        <label>排序<input v-model.number="order" type="number" min="0" max="9999" step="1" required /></label>
        <label>分类说明<textarea v-model="description" maxlength="200" rows="3" placeholder="可留空" /></label>
      </fieldset>
      <p class="category-hint">排序值越小越靠前。同一所属分类下不能重名，创建后立即可选。</p>
      <p v-if="error" role="alert" class="category-error">{{ error }}</p>
    </form>
    <template #footer><div class="category-footer"><button :disabled="saving" @click="close()">取消</button><button class="primary" type="submit" form="category-create-form" :disabled="saving || loading || !!loadError">{{ saving?'正在创建…':'创建分类' }}</button></div></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ContentState from './ContentState.vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import type { CategoryRow } from '@/utils/categories'
const visible=defineModel<boolean>({default:false})
const emit=defineEmits<{created:[row:CategoryRow]}>()
const name=ref(''),parent=ref('0'),order=ref(0),description=ref(''),rows=ref<CategoryRow[]>([])
const saving=ref(false),loading=ref(false),error=ref(''),loadError=ref(''),gate=latestRequest()
let disposed=false
const roots=computed(()=>rows.value.filter(r=>r.parentId==='0' && r.status===1))
const message=(e:unknown)=>e instanceof Error?e.message:'操作失败，请重试'
async function load(){const run=gate.begin();loading.value=true;loadError.value='';try{const result:any=await request.get('/admin/categories',{signal:run.signal});if(run.isCurrent() && !disposed)rows.value=result.data}catch(e){if(run.isCurrent() && !disposed)loadError.value=message(e)}finally{if(run.isCurrent() && !disposed)loading.value=false}}
async function save(){
  if(saving.value || loading.value || loadError.value)return
  if(!name.value.trim()){error.value='请填写分类名称';return}
  saving.value=true;error.value=''
  try{const result:any=await request.post('/admin/categories',{categoryName:name.value.trim(),parentId:parent.value,sortOrder:order.value,description:description.value.trim()});if(disposed)return;emit('created',result.data);visible.value=false;ElMessage.success('分类已创建')}
  catch(e){if(!disposed)error.value=message(e)}finally{if(!disposed)saving.value=false}
}
function close(done?:()=>void){if(saving.value)return;gate.cancel();visible.value=false;done?.()}
watch(visible,value=>{if(value){name.value='';parent.value='0';order.value=0;description.value='';error.value='';void load()}else gate.cancel()})
onUnmounted(()=>{disposed=true;gate.cancel()})
</script>
<style scoped>
.category-form fieldset{border:0;padding:0;margin:0;display:grid;gap:18px}.category-form label{display:grid;gap:8px;font-size:13px}.category-form input,.category-form select,.category-form textarea{font:inherit;padding:11px 12px;border:1px solid var(--ej-line);border-radius:10px;color:var(--ej-ink);background:var(--ej-canvas);width:100%;box-sizing:border-box}.category-form textarea{resize:vertical}.category-hint{font-size:12px;color:var(--ej-muted);line-height:1.8}.category-error{font-size:13px;color:#b44a36}.category-footer{display:flex;justify-content:flex-end;gap:10px}.category-footer button{font:inherit;border:1px solid var(--ej-line);border-radius:99px;padding:10px 18px;background:var(--ej-surface);cursor:pointer}.category-footer .primary{background:var(--ej-ink);color:var(--ej-surface)}.category-footer button:disabled{opacity:.5;cursor:not-allowed}
</style>
