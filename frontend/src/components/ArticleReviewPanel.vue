<template>
  <section class="review-panel">
    <div class="review-toolbar"><p>逐版本审核，已发布文章的修改通过后才会替换公开内容。</p><select v-model.number="state" aria-label="审核状态" @change="page=1;load()"><option :value="1">待审核</option><option :value="2">已通过</option><option :value="3">已驳回</option><option :value="4">已撤回</option></select><button @click="load">刷新</button></div>
    <ContentState v-if="loading" kind="loading" title="正在加载审核队列" />
    <ContentState v-else-if="error" kind="error" title="审核队列加载失败" :description="error" @retry="load" />
    <ContentState v-else-if="!rows.length" kind="empty" title="暂无审核记录" />
    <div v-else class="review-table-wrap"><table><thead><tr><th>文章</th><th>作者</th><th>版本</th><th>提交于</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.revisionId"><td><strong>{{ row.title }}</strong><small v-if="row.reason">驳回原因：{{ row.reason }}</small></td><td>{{ row.authorName }}</td><td>V{{ row.version }}</td><td>{{ time(row.submittedAt) }}</td><td><button :disabled="detailLoading" @click="open(row.revisionId)">{{ state===1?'查看并审核':'查看记录' }}</button></td></tr></tbody></table></div>
    <div class="review-pagination"><span>共 {{ total }} 条</span><button :disabled="loading || page<=1" @click="page--;load()">上一页</button><span>{{ page }} / {{ Math.max(1,pages) }}</span><button :disabled="loading || page>=pages" @click="page++;load()">下一页</button></div>
    <el-dialog v-model="visible" title="文章版本审核" width="min(1200px, 94vw)" :close-on-click-modal="false" destroy-on-close>
      <ContentState v-if="detailLoading" kind="loading" title="正在加载完整版本" />
      <template v-else-if="detail">
        <div class="review-version-note">V{{ detail.version }} · {{ revisionLabel(detail.state) }} · 内容校验 {{ detail.contentHash?.slice(0,12) }}<p v-if="!detail.hasPublishedVersion">首次发布，审核通过前社区无法阅读。</p><p v-else>左侧为提交时的公开基准版本，右侧为本次提交。审核通过后替换正文，保留文章 ID、发布时间和互动数据。</p></div>
        <div class="review-comparison"><section v-if="detail.publicPayload"><h3>公开基准版</h3><ReviewContent :payload="detail.publicPayload" /></section><section><h3>提交版 V{{ detail.version }}</h3><ReviewContent :payload="detail.payload" /></section></div>
        <p v-if="detail.reason" class="review-reason">审核意见：{{ detail.reason }}</p>
        <div v-if="detail.state===1" class="review-decision"><label>审核意见（驳回时必填）<textarea v-model="reason" maxlength="1000" rows="3" placeholder="说明需要修改的地方，作者可以看到这条意见" /></label><div><button :disabled="busy" @click="decide('reject')">驳回</button><button class="approve" :disabled="busy" @click="decide('approve')">通过审核</button></div></div>
        <details class="review-audit"><summary>审核轨迹</summary><p v-for="log in detail.logs" :key="log.id">{{ time(log.createdAt) }} · {{ actionLabel(log.action) }} · {{ log.reason || '—' }}</p></details>
      </template>
    </el-dialog>
  </section>
</template>
<script setup lang="ts">
import { defineComponent,h,onMounted,onUnmounted,ref } from 'vue'
import request from '@/utils/request'
import ContentState from '@/components/ContentState.vue'
import { safeHtml } from '@/utils/safeHtml'
import { latestRequest } from '@/utils/latestRequest'
import { notify,confirmAction,errorMessage } from '@/utils/feedback'
const emit=defineEmits(['changed'])
const ReviewContent=defineComponent({props:['payload'],setup(props){return()=>h('div',{class:'review-content'},[
  h('h2',props.payload.title),h('p',props.payload.summary || ''),
  h('p',{class:'review-content-meta'},`分类 ${props.payload.categoryName || '未选择'} · ${props.payload.isOriginal?'原创':'转载'} · ${(props.payload.tagNames || []).join(' / ')}`),
  props.payload.coverImage?h('img',{src:props.payload.coverImage,alt:'版本封面'}):null,
  props.payload.contentType===2?h('pre',props.payload.content):h('div',{innerHTML:safeHtml(props.payload.content)})])}})
const state=ref(1),page=ref(1),pages=ref(0),total=ref(0),rows=ref<any[]>([]),loading=ref(false),error=ref('')
const visible=ref(false),detail=ref<any>(),reason=ref(''),busy=ref(false),detailLoading=ref(false)
const listGate=latestRequest(),detailGate=latestRequest()
const time=(value:string)=>value?value.replace('T',' ').slice(0,16):'—'
const revisionLabel=(value:number)=>({0:'草稿',1:'待审核',2:'已通过',3:'已驳回',4:'已撤回',5:'已替换'}[value] || '未知')
const actionLabel=(value:string)=>({submit:'提交',withdraw:'撤回',approve:'通过',reject:'驳回',discard:'丢弃修改'}[value] || value)
async function load(){const run=listGate.begin();loading.value=true;error.value='';try{const result:any=await request.get('/admin/reviews',{params:{state:state.value,page:page.value,size:20},signal:run.signal});if(run.isCurrent()){rows.value=result.data.records;total.value=result.data.total;pages.value=result.data.pages}}catch(e){if(run.isCurrent())error.value=errorMessage(e,'加载失败')}finally{if(run.isCurrent())loading.value=false}}
async function open(id:string){const run=detailGate.begin();visible.value=true;detail.value=undefined;detailLoading.value=true;reason.value='';try{const result:any=await request.get(`/admin/reviews/${id}`,{signal:run.signal});if(run.isCurrent())detail.value=result.data}catch(e){if(run.isCurrent()){notify.error(errorMessage(e,'版本加载失败'));visible.value=false}}finally{if(run.isCurrent())detailLoading.value=false}}
async function decide(decision:'approve'|'reject'){
  if(!detail.value || busy.value)return
  if(decision==='reject' && !reason.value.trim()){notify.warning('请填写驳回原因');return}
  if(!await confirmAction(decision==='approve'?'确认通过这个版本？通过后将更新社区公开内容。':'确认驳回这个版本？作者可以修改后再次提交。','审核确认'))return
  busy.value=true;try{await request.post(`/admin/reviews/${detail.value.revisionId}`,{decision,reason:reason.value.trim()});notify.success('审核已提交');visible.value=false;await load();emit('changed')}catch(e){notify.error(errorMessage(e,'审核失败'));await open(detail.value.revisionId);await load()}finally{busy.value=false}
}
onMounted(load);onUnmounted(()=>{listGate.cancel();detailGate.cancel()})
defineExpose({reload:load})
</script>
<style scoped>
.review-panel{padding:24px;border:1px solid var(--ej-line);border-radius:18px;background:var(--ej-surface)}.review-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px}.review-toolbar p{flex:1;font-size:13px;color:var(--ej-muted);line-height:1.8}.review-panel button,.review-panel select{border:1px solid var(--ej-line);border-radius:12px;background:var(--ej-surface);padding:9px 14px;color:var(--ej-ink);cursor:pointer;white-space:nowrap}.review-panel button:disabled{opacity:.4;cursor:not-allowed}.review-table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}td,th{padding:16px 12px;border-bottom:1px solid var(--ej-hairline)}th{color:var(--ej-muted);font-weight:500}td small{display:block;color:#b44a36;margin-top:6px}.review-pagination{display:flex;align-items:center;gap:12px;margin-top:22px;font-size:12px}.review-pagination>span:first-child{margin-right:auto}.review-version-note{font-size:12px;color:var(--ej-muted)}.review-comparison{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:20px;margin:20px 0}.review-comparison section{min-width:0;border:1px solid var(--ej-hairline);border-radius:12px;padding:20px}.review-comparison h3{margin:0 0 16px;color:var(--ej-muted);font-size:13px}.review-comparison :deep(img){max-width:100%;max-height:360px;object-fit:contain}.review-comparison :deep(pre){white-space:pre-wrap;overflow-wrap:anywhere}.review-comparison :deep(.review-content){line-height:1.8;overflow-wrap:anywhere}.review-comparison :deep(.review-content-meta){font-size:12px;color:var(--ej-muted)}.review-decision label{display:block;font-size:13px}.review-decision textarea{display:block;box-sizing:border-box;width:100%;margin:10px 0;border:1px solid var(--ej-line);border-radius:12px;padding:12px;background:var(--ej-surface);color:var(--ej-ink);font:inherit}.review-decision>div{display:flex;justify-content:flex-end;gap:12px}.review-decision .approve{background:var(--studio-lime);color:var(--ej-ink)}.review-reason{color:#b44a36}.review-audit{margin-top:24px;font-size:12px;color:var(--ej-muted)}@media(max-width:600px){.review-panel{padding:16px}.review-toolbar p{flex-basis:100%}}
</style>
