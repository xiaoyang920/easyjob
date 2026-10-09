<template>
 <el-dialog v-model="visible" title="推荐偏好" width="min(620px,94vw)" align-center :close-on-click-modal="false">
  <p class="preference-note">这些反馈仅影响推荐列表。最多保留200条，随时可以恢复。</p>
  <ContentState v-if="loading" kind="loading" title="正在加载偏好" /><ContentState v-else-if="error" kind="error" title="加载失败" :description="error" @retry="reload" /><ContentState v-else-if="!rows.length" kind="empty" title="暂未隐藏任何推荐" />
  <div v-else class="preference-list"><article v-for="row in rows" :key="row.articleId"><div><strong>{{ row.kind==='hide_author'?`减少来自 ${row.authorName || '该作者'} 的推荐`:row.title || '原文章已删除' }}</strong><p>{{ row.kind==='hide_author'?'不再推荐该作者的文章':'对这篇文章不感兴趣' }}</p></div><button :disabled="!!busy" @click="restore(row.articleId)">{{ busy===row.articleId?'恢复中…':'恢复推荐' }}</button></article></div>
 </el-dialog>
</template>
<script setup lang="ts">
import { ref,watch,onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import ContentState from './ContentState.vue'
import { latestRequest } from '@/utils/latestRequest'
const visible=defineModel<boolean>({default:false}),emit=defineEmits<{changed:[]}>(),rows=ref<{articleId:string;kind:string;title:string;authorName:string}[]>([]),loading=ref(false),error=ref(''),busy=ref(''),gate=latestRequest();let disposed=false
async function reload(){const run=gate.begin();loading.value=true;error.value='';try{const result:any=await request.get('/recommendation/feedback',{signal:run.signal});if(run.isCurrent() && !disposed)rows.value=result.data}catch(e){if(run.isCurrent() && !disposed)error.value=e instanceof Error?e.message:'请求失败'}finally{if(run.isCurrent() && !disposed)loading.value=false}}
async function restore(id:string){if(busy.value)return;busy.value=id;try{await request.delete(`/recommendation/feedback/${id}`);if(disposed)return;rows.value=rows.value.filter(r=>r.articleId!==id);emit('changed');ElMessage.success('已恢复推荐')}catch(e){if(!disposed)ElMessage.error(e instanceof Error?e.message:'恢复失败')}finally{if(!disposed)busy.value=''}}
watch(visible,v=>{if(v)void reload();else gate.cancel()});onUnmounted(()=>{disposed=true;gate.cancel()})
</script>
<style scoped>
.preference-note,.preference-list p{font-size:12px;color:var(--ej-muted);line-height:1.8}.preference-list{max-height:55vh;overflow:auto}.preference-list article{display:flex;justify-content:space-between;align-items:center;gap:18px;padding:18px 0;border-bottom:1px solid var(--ej-hairline)}.preference-list strong{font-size:14px;overflow-wrap:anywhere}.preference-list button{flex-shrink:0;font:inherit;font-size:12px;background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:99px;padding:9px 14px;cursor:pointer}
</style>
