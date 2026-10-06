<template>
  <div class="operations">
    <p v-if="error" class="feedback" role="alert">{{ error }}</p>
    <div class="metrics">
      <div v-for="item in metrics" :key="item.label"><small>{{ item.label }}</small><strong>{{ item.value }}</strong></div>
    </div>
    <section class="panel">
      <h2>索引对账</h2><p>后台分批比对数据库与搜索索引，发现差异后提交修复任务。失败任务达到重试上限后由管理员处理。</p>
      <div class="sweeps">
        <div v-for="item in summary?.reconciliation || []" :key="item.kind">
          <header><strong>{{ kindName(item.kind) }}</strong><span>{{ item.running ? '检查中' : '等待检查' }}</span></header>
          <p>累计检查 {{ item.scanned }} · 提交修复 {{ item.repaired }}</p>
          <small>最近检查 {{ time(item.finishedAt) }}<br>下次检查 {{ time(item.nextAt) }}</small>
          <p v-if="item.error" class="feedback">错误码：{{ item.error }}</p>
          <button :disabled="!!busy || !!item.running" @click="reconcile(item.kind)">安排检查 ↗</button>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="filters"><div class="tabs"><button v-for="item in tabs" :key="item.key" :class="{active:tab===item.key}" @click="changeTab(item.key)">{{ item.label }}</button></div>
        <select v-model="state" aria-label="运行或任务状态" @change="page=1;loadRows()"><option v-for="s in states" :key="s" :value="s">{{ statusName(s) }}</option></select>
      </div>
      <p class="note">仅展示运行状态和任务标识。重试将重新核验当前数据，不会重新执行整轮 AI 对话。</p>
      <ContentState v-if="loading" kind="loading" title="正在读取运行状态" />
      <ContentState v-else-if="rowsError" kind="error" title="状态暂时无法加载" :description="rowsError" @retry="loadRows" />
      <ContentState v-else-if="!rows.length" kind="empty" title="暂无匹配记录" />
      <div v-else class="table-wrap"><table><thead><tr><th>标识 / 类型</th><th>{{ tab==='runs'?'用户 / 会话':'目标 ID' }}</th><th>状态</th><th>{{ tab==='runs'?'创建时间':'重试次数' }}</th><th>更新时间</th><th>{{ tab==='runs'?'截止时间':'错误 / 操作' }}</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.runId || row.jobId"><td><code>{{ row.runId || row.jobId }}</code><small>{{ row.kind }}</small></td><td>{{ row.userId || row.targetId }}<small v-if="row.conversationId">{{ row.conversationId }}</small></td><td><span :class="['status',row.status]">{{ statusName(row.status) }}</span></td><td>{{ tab==='runs'?time(row.createdAt):row.attempts }}</td><td>{{ time(row.updatedAt) }}</td><td v-if="tab==='runs'">{{ time(row.deadline) }}</td><td v-else><small v-if="row.error && row.status==='dead'">{{ row.error }}</small><span v-if="row.status==='dead' && tab==='memory' && !['memory_write','memory_index','checkpoint_cleanup'].includes(row.kind || '')">已停用</span><button v-else-if="row.status==='dead'" :disabled="!!busy" @click="retry(row)">{{ busy===row.jobId?'提交中…':'重试任务' }}</button></td></tr></tbody>
      </table></div>
      <footer><span>共 {{ total }} 条</span><div><button :disabled="loading || page<=1" @click="page--;loadRows()">上一页</button><span>{{ page }} / {{ Math.max(1,pages) }}</span><button :disabled="loading || page>=pages" @click="page++;loadRows()">下一页</button></div></footer>
    </section>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import ContentState from './ContentState.vue'
type Tab='article'|'memory'|'runs'
type Row={runId?:string;jobId?:string;kind?:string;userId?:string;targetId?:string;conversationId?:string;status:string;attempts?:number;createdAt?:string;updatedAt?:string;deadline?:string;error?:string}
type Summary={article:{status:string;count:number}[];memory:{status:string;count:number}[];runs:{status:string;count:number}[];views:{pending:number};reconciliation:{kind:string;scanned:number;repaired:number;running:boolean;error?:string;finishedAt?:string;nextAt?:string}[]}
const tabs=[{key:'article' as Tab,label:'文章索引任务'},{key:'memory' as Tab,label:'记忆与清理任务'},{key:'runs' as Tab,label:'AI 运行'}]
const tab=ref<Tab>('article'),state=ref('dead'),page=ref(1),total=ref(0),pages=ref(0)
const summary=ref<Summary>(),rows=ref<Row[]>([]),loading=ref(false),error=ref(''),rowsError=ref(''),busy=ref('')
const gate=latestRequest();let disposed=false,refreshing=false,timer:ReturnType<typeof setInterval>|undefined
const states=computed(()=>tab.value==='runs'?['all','running','awaiting_approval','succeeded','failed','cancelled','expired']:['all','pending','running',...(tab.value==='article'?['dispatched']:[]),'completed','dead'])
const count=(queue:'article'|'memory'|'runs',states:string[])=>summary.value?.[queue]?.filter(r=>states.includes(r.status)).reduce((n,r)=>n+Number(r.count),0)??'—'
const metrics=computed(()=>[{label:'文章待处理',value:count('article',['pending','running','dispatched'])},{label:'记忆待处理',value:count('memory',['pending','running'])},{label:'终止的失败任务',value:summary.value?Number(count('article',['dead']))+Number(count('memory',['dead'])):'—'},{label:'近 24 小时运行中',value:count('runs',['running'])},{label:'阅读量待同步',value:summary.value?.views.pending??'—'}])
const statusName=(s:string)=>({all:'全部',pending:'待处理',running:'运行中',dispatched:'等待确认',completed:'已完成',dead:'重试已终止',awaiting_approval:'等待审批',succeeded:'成功',failed:'失败',cancelled:'已取消',expired:'已过期'}[s]||s)
const kindName=(s:string)=>({article:'文章内容与分块',memory:'决策记忆',article_orphan:'已删除文章',memory_orphan:'已删除记忆',chunk_orphan:'残留文章分块'}[s]||s)
const time=(s?:string)=>s?new Date(/[zZ]|[+-]\d\d:\d\d$/.test(s)?s:s.replace(' ','T')+'Z').toLocaleString('zh-CN',{hour12:false}):'—'
const message=(e:unknown)=>e instanceof Error?e.message:'请求失败，请稍后重试'
async function loadSummary(){try{const r:any=await request.get('/admin/operations');if(!disposed){summary.value=r.data;error.value=''}}catch(e){if(!disposed)error.value=message(e)}}
async function loadRows(){const run=gate.begin();loading.value=true;rowsError.value='';try{const r:any=await request.get(`/admin/operations/${tab.value==='runs'?'runs':'jobs'}`,{params:{queue:tab.value,state:state.value,page:page.value,size:20},signal:run.signal});if(run.isCurrent()&&!disposed){rows.value=r.data.records;total.value=r.data.total;pages.value=r.data.pages}}catch(e){if(run.isCurrent()&&!disposed)rowsError.value=message(e)}finally{if(run.isCurrent()&&!disposed)loading.value=false}}
async function reload(){if(refreshing||disposed)return;refreshing=true;try{await Promise.all([loadSummary(),loadRows()])}finally{refreshing=false}}
function changeTab(next:Tab){tab.value=next;state.value=next==='runs'?'all':'dead';page.value=1;void loadRows()}
async function retry(row:Row){const queue=tab.value;if(queue==='runs'||!row.jobId)return;try{await ElMessageBox.confirm('重新核验最新数据并执行该后台任务，操作会记入管理日志。','重试失败任务',{confirmButtonText:'重试',cancelButtonText:'取消'})}catch{return}busy.value=row.jobId;try{await request.post(`/admin/operations/jobs/${queue}/${row.jobId}/retry`);ElMessage.success('已加入重试队列');await reload()}catch(e){ElMessage.error(message(e))}finally{busy.value=''}}
async function reconcile(kind:string){busy.value=kind;try{await request.post('/admin/operations/reconcile',{kind});ElMessage.success('已安排后台检查');await loadSummary()}catch(e){ElMessage.error(message(e))}finally{busy.value=''}}
onMounted(()=>{void reload();timer=setInterval(()=>{if(!document.hidden&&!busy.value&&!loading.value)void reload()},10000)})
onUnmounted(()=>{disposed=true;gate.cancel();clearInterval(timer)})
defineExpose({reload})
</script>
<style scoped>
.operations{display:grid;gap:20px}.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.metrics>div,.panel{background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:18px;padding:20px}.metrics strong{display:block;font-size:28px;margin-top:14px}.metrics small,.panel p,.note{font-size:12px;color:var(--ej-muted);line-height:1.8}.panel h2{font-size:17px;margin:0}.sweeps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:20px}.sweeps>div{padding:16px;border:1px solid var(--ej-hairline);border-radius:14px}.sweeps header{display:flex;justify-content:space-between;gap:10px;font-size:13px}.sweeps header span,.sweeps small{font-size:11px;color:var(--ej-muted)}.sweeps button{margin-top:16px}.filters{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.tabs{display:flex;gap:8px;flex-wrap:wrap}button,select{font:inherit;font-size:12px;border:1px solid var(--ej-line);background:var(--ej-surface);border-radius:99px;padding:9px 14px;color:inherit}button{cursor:pointer;transition:background .18s}button:hover:enabled,button.active{background:var(--studio-lime)}button:disabled{opacity:.4;cursor:not-allowed}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px;text-align:left}td,th{padding:14px 10px;border-bottom:1px solid var(--ej-hairline);white-space:nowrap}th{font-weight:500;color:var(--ej-muted)}td small{display:block;color:var(--ej-muted);margin-top:5px}code{display:block;max-width:240px;overflow-wrap:anywhere;white-space:normal;font-size:11px}.status{border-radius:99px;background:var(--ej-canvas);padding:5px 8px}.status.dead,.status.failed{background:#f7ded5}.status.running,.status.succeeded{background:var(--studio-lime-soft)}footer,footer>div{display:flex;align-items:center;gap:12px}footer{justify-content:space-between;margin-top:22px;font-size:12px;color:var(--ej-muted)}.feedback{color:#b44a36!important;font-size:12px}@media(max-width:900px){.metrics{grid-template-columns:repeat(2,1fr)}.panel{padding:16px}}
</style>
