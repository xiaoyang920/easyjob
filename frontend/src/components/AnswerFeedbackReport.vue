<template>
 <section class="feedback-report"><h2>回答反馈</h2><p>用户主动提交的反馈，不等同于准确率；真实业务与评测样例分别统计。</p>
  <ContentState v-if="error" kind="error" title="反馈暂时无法加载" :description="error" @retry="load" /><ContentState v-else-if="loading" kind="loading" title="正在读取反馈" />
  <template v-else><div class="feedback-totals"><span v-for="item in counts" :key="item.rating+item.reason">{{ label(item.rating,item.reason) }} {{ item.count }}</span></div><p v-if="!rows.length">暂无反馈</p>
   <article v-for="row in rows" :key="row.run_id"><span>{{ label(row.rating,row.reason) }}</span><code :title="row.run_id">{{ row.run_id }}</code><span :class="['review-state',row.review_state]">{{ row.review_state==='resolved'?'已解决':'待处理' }}</span><time>{{ row.updated_at?.replace('T',' ').slice(0,19) }}</time><button v-if="canRead" type="button" @click="selectedRun=row.run_id">查看详情</button></article>
   <p v-if="!canRead">当前账号可查看统计；查看问答内容需要反馈查看权限。</p><div class="feedback-pages"><button :disabled="page===1" @click="page--;load()">上一页</button><span>第 {{ page }} 页 · 共 {{ total }} 条</span><button :disabled="page*20>=total" @click="page++;load()">下一页</button></div>
  </template><AnswerFeedbackDetail :run-id="selectedRun" :can-manage="canManage" @close="selectedRun=''" @updated="load" />
 </section>
</template>
<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue';import request from '@/utils/request';import {latestRequest} from '@/utils/latestRequest'
import ContentState from './ContentState.vue'
import AnswerFeedbackDetail from './AnswerFeedbackDetail.vue'
const props=withDefaults(defineProps<{source:string;canRead?:boolean;canManage?:boolean}>(),{canRead:false,canManage:false}),rows=ref<any[]>([]),counts=ref<any[]>([]),total=ref(0),page=ref(1),loading=ref(false),error=ref(''),gate=latestRequest(),selectedRun=ref('')
function label(rating:string,reason:string){return rating==='helpful'?'有帮助':({'irrelevant':'答非所问','incorrect':'事实或推理错误','citation':'引用有误','incomplete':'回答不完整','other':'其他问题'}[reason]||'有问题')}
async function load(){const run=gate.begin();loading.value=true;error.value='';try{const r:any=await request.get('/admin/agent-feedback',{params:{page:page.value,size:20,source:props.source},signal:run.signal});if(run.isCurrent()){rows.value=r.data.rows;counts.value=r.data.counts;total.value=r.data.total??r.data.rows.length}}catch(e){if(run.isCurrent())error.value=e instanceof Error?e.message:'读取失败'}finally{if(run.isCurrent())loading.value=false}}
watch(()=>props.source,()=>{page.value=1;selectedRun.value='';void load()},{immediate:true});onUnmounted(()=>gate.cancel());defineExpose({load})
</script>
<style scoped>.feedback-report article{flex-wrap:wrap}.review-state{font-size:11px;padding:5px 9px;border-radius:99px;background:var(--ej-canvas)}.review-state.resolved{background:var(--studio-lime-soft)}.feedback-report article code{min-width:120px;overflow-wrap:anywhere;font-size:11px}.feedback-pages{flex-wrap:wrap}.feedback-report button:disabled{opacity:.45;cursor:not-allowed}</style>
<style scoped>.feedback-report{margin-top:24px;padding:24px;border:1px solid var(--ej-line);border-radius:18px;background:var(--ej-surface)}h2{font-size:18px}p,time{font-size:12px;color:var(--ej-muted)}.feedback-totals{display:flex;gap:12px;flex-wrap:wrap}.feedback-totals span{padding:8px;border-radius:8px;background:var(--ej-canvas)}article{display:flex;gap:18px;align-items:center;border-bottom:1px solid var(--ej-line);padding:16px 0;font-size:13px}article code{flex:1;overflow:hidden;text-overflow:ellipsis}.feedback-pages{display:flex;gap:16px;align-items:center;margin-top:16px}button{border:1px solid var(--ej-line);border-radius:99px;padding:6px 12px;background:transparent;cursor:pointer}</style>
