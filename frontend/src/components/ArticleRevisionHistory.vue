<template>
  <el-dialog v-model="visible" title="文章版本历史" width="min(960px,94vw)" destroy-on-close>
    <ContentState v-if="loading" kind="loading" title="正在读取版本历史" />
    <ContentState v-else-if="error" kind="error" title="版本加载失败" :description="error" @retry="load" />
    <ContentState v-else-if="!rows.length" kind="empty" title="这篇文章尚未保存版本快照" />
    <div v-else class="revision-history"><aside><button v-for="row in rows" :key="row.revisionId" :class="{selected:selected?.revisionId===row.revisionId}" @click="select(row.revisionId)">V{{ row.version }} · {{ label(row.state) }}<small>{{ row.createdAt?.replace('T',' ').slice(0,16) }}</small></button></aside><section v-if="selected"><h2>{{ selected.payload.title }}</h2><p v-if="selected.reason" class="reason">审核意见：{{ selected.reason }}</p><p>{{ selected.payload.summary }}</p><pre v-if="selected.payload.contentType===2">{{ selected.payload.content }}</pre><div v-else v-html="safeHtml(selected.payload.content)" /><RevisionComparison :article-id="articleId" :selected="selected" :versions="rows" /><button class="restore" :disabled="busy || pending" @click="restore">基于此版本创建修改草稿</button><p class="note">恢复历史内容会更新工作草稿，审核通过后才会更新公开文章。</p></section></div>
  </el-dialog>
</template>
<script setup lang="ts">
import { ref,watch,onUnmounted } from 'vue'
import request from '@/utils/request'
import {safeHtml} from '@/utils/safeHtml'
import {latestRequest} from '@/utils/latestRequest'
import {notify,confirmAction,errorMessage} from '@/utils/feedback'
import ContentState from '@/components/ContentState.vue'
import RevisionComparison from '@/components/RevisionComparison.vue'
const props=defineProps<{articleId:string;revisionId:string;lockVersion:number;initialRevisionId?:string;pending:boolean;modelValue:boolean}>()
const emit=defineEmits(['update:modelValue','restored'])
const visible=ref(props.modelValue),rows=ref<any[]>([]),selected=ref<any>(),loading=ref(false),error=ref(''),busy=ref(false)
const listGate=latestRequest(),detailGate=latestRequest()
const label=(value:number)=>({0:'草稿',1:'待审核',2:'已通过',3:'已驳回',4:'已撤回',5:'已替换'}[value] || '未知')
watch(()=>props.modelValue,value=>{visible.value=value;if(value)void load()},{immediate:true});watch(visible,value=>emit('update:modelValue',value))
async function load(){const run=listGate.begin();loading.value=true;error.value='';selected.value=undefined;try{const result:any=await request.get(`/article/${props.articleId}/revisions`,{signal:run.signal});if(run.isCurrent()){rows.value=result.data;if(props.initialRevisionId || rows.value.length)await select(props.initialRevisionId || rows.value[0].revisionId);if(run.isCurrent() && selected.value && !rows.value.some(r=>r.revisionId===selected.value.revisionId))rows.value.unshift(selected.value)}}catch(e){if(run.isCurrent())error.value=errorMessage(e,'加载失败')}finally{if(run.isCurrent())loading.value=false}}
async function select(id:string){const run=detailGate.begin();try{const result:any=await request.get(`/article/${props.articleId}/revisions/${id}`,{signal:run.signal});if(run.isCurrent())selected.value=result.data}catch(e){if(run.isCurrent())notify.error(errorMessage(e,'版本加载失败'))}}
async function restore(){if(!selected.value || busy.value || props.pending)return;if(!await confirmAction('根据这个版本创建新草稿？当前公开内容保持不变。','恢复历史版本'))return;busy.value=true;try{await request.post(`/article/${props.articleId}/revisions/${selected.value.revisionId}/restore`,{expectedRevisionId:props.revisionId,expectedLockVersion:props.lockVersion});notify.success('已创建修改草稿');visible.value=false;emit('restored')}catch(e){notify.error(errorMessage(e,'恢复失败，请刷新'))}finally{busy.value=false}}
onUnmounted(()=>{listGate.cancel();detailGate.cancel()})
</script>
<style scoped>
.revision-history{display:grid;grid-template-columns:180px minmax(0,1fr);gap:24px}.revision-history aside button{display:block;width:100%;text-align:left;margin-bottom:8px;padding:12px;border:1px solid var(--ej-line);border-radius:12px;background:var(--ej-surface);color:var(--ej-ink);cursor:pointer}.revision-history aside button.selected{background:var(--studio-lime)}.revision-history small{display:block;color:var(--ej-muted);font-size:11px;margin-top:6px}.revision-history section{line-height:1.8;overflow-wrap:anywhere}.revision-history :deep(img){max-width:100%;height:auto}.revision-history pre{white-space:pre-wrap}.reason{color:#b44a36}.restore{margin-top:20px;padding:10px 16px;border:1px solid var(--ej-line);border-radius:99px;background:var(--ej-surface);cursor:pointer}.restore:disabled{opacity:.4}.note{font-size:12px;color:var(--ej-muted)}@media(max-width:600px){.revision-history{grid-template-columns:1fr}.revision-history aside{display:flex;overflow-x:auto;gap:8px}.revision-history aside button{flex:0 0 150px}}
</style>
