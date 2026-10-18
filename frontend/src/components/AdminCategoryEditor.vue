<template>
  <el-dialog v-model="visible" :title="mode==='edit'?'编辑分类':'迁移分类文章'" width="min(580px,94vw)" align-center :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" :before-close="close" append-to-body class="ej-dialog">
    <form v-if="row" id="category-edit-form" class="category-editor" @submit.prevent="save">
      <fieldset :disabled="saving">
        <template v-if="mode==='edit'"><label>名称<input v-model="name" required maxlength="50" /></label><label>排序<input v-model.number="order" type="number" min="0" max="9999" step="1" required /></label><label>说明<textarea v-model="description" rows="3" maxlength="200" /></label><label>状态<AppSelect v-model.number="status"><AppSelectOption :value="1" :disabled="!!row.migratedTo">启用</AppSelectOption><AppSelectOption :value="0">停用</AppSelectOption></AppSelect></label><p>停用后不再提供新文章选择，已有文章保留原分类。一级分类需先处理启用的二级分类。</p><p v-if="row.migratedTo">已迁移至 {{ names.get(row.migratedTo) || row.migratedTo }}，原分类保留历史关联，不能重新启用。</p></template>
        <template v-else><p>将“{{ row.categoryName }}”下 {{ row.articleCount || 0 }} 篇未删除文章迁入目标分类，包括草稿和已下架文章。原分类将停用，历史版本保留，后续草稿和审批会使用新分类。</p><label>目标分类<AppSelect v-model="target" required><AppSelectOption value="">请选择目标分类</AppSelectOption><AppSelectOption v-for="item in targets" :key="item.categoryId" :value="item.categoryId">{{ item.parentId==='0'?'':`${names.get(item.parentId)} / ` }}{{ item.categoryName }}</AppSelectOption></AppSelect></label><p>启用的二级分类需先单独处理。一次操作最多迁移 500 篇。</p></template>
      </fieldset><p v-if="error" role="alert" class="category-editor-error">{{ error }}</p>
    </form>
    <template #footer><div class="category-editor-footer"><button :disabled="saving" @click="close()">取消</button><button class="primary" type="submit" form="category-edit-form" :disabled="saving || (mode==='move' && !target)">{{ saving?'正在处理…':mode==='edit'?'保存修改':'确认迁移并停用原分类' }}</button></div></template>
  </el-dialog>
</template>
<script setup lang="ts">
import { computed,onUnmounted,ref,watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { CategoryRow } from '@/utils/categories'
import request from '@/utils/request'
const visible=defineModel<boolean>({default:false})
const props=defineProps<{row?:CategoryRow;rows:CategoryRow[];mode:'edit'|'move'}>(),emit=defineEmits<{changed:[]}>()
const name=ref(''),order=ref(0),description=ref(''),status=ref(1),target=ref(''),saving=ref(false),error=ref('')
let disposed=false
const names=computed(()=>new Map(props.rows.map(r=>[r.categoryId,r.categoryName])))
const targets=computed(()=>props.rows.filter(r=>r.categoryId!==props.row?.categoryId && r.status===1 && !r.migratedTo && (r.parentId==='0' || props.rows.some(p=>p.categoryId===r.parentId && p.status===1))))
watch(visible,value=>{if(value && props.row){name.value=props.row.categoryName;order.value=props.row.sortOrder;description.value=props.row.description || '';status.value=props.row.status;target.value='';error.value=''}})
function close(done?:()=>void){if(saving.value)return;visible.value=false;done?.()}
async function save(){
  if(saving.value || !props.row)return
  saving.value=true;error.value=''
  try{
    if(props.mode==='edit')await request.put(`/admin/categories/${props.row.categoryId}`,{expectedVersion:props.row.version,categoryName:name.value.trim(),sortOrder:order.value,description:description.value.trim(),status:status.value})
    else{const selected=targets.value.find(r=>r.categoryId===target.value);if(!selected)throw new Error('请选择有效目标分类');await request.post(`/admin/categories/${props.row.categoryId}/migrate`,{expectedVersion:props.row.version,targetId:selected.categoryId,targetVersion:selected.version})}
    if(disposed)return;visible.value=false;emit('changed');ElMessage.success(props.mode==='edit'?'分类已更新':'分类文章已迁移')
  }catch(e){if(!disposed)error.value=e instanceof Error?e.message:'操作失败，请重试'}finally{if(!disposed)saving.value=false}
}
onUnmounted(()=>{disposed=true})
</script>
<style scoped>
.category-editor fieldset{border:0;padding:0;margin:0;display:grid;gap:16px}.category-editor label{display:grid;gap:8px;font-size:13px}.category-editor input,.category-editor textarea,.category-editor select{font:inherit;padding:11px;border:1px solid var(--ej-line);border-radius:10px;background:var(--ej-canvas);width:100%;box-sizing:border-box}.category-editor p{font-size:12px;color:var(--ej-muted);line-height:1.8;margin:0}.category-editor .category-editor-error{color:#b44a36;margin-top:14px}.category-editor-footer{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:10px}.category-editor-footer button{font:inherit;border:1px solid var(--ej-line);border-radius:99px;background:var(--ej-surface);padding:10px 16px;cursor:pointer}.category-editor-footer .primary{background:var(--ej-ink);color:var(--ej-surface)}.category-editor-footer button:disabled{opacity:.5;cursor:not-allowed}
</style>
