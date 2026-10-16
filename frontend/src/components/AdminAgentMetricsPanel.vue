<template>
 <section class="agent-metrics-panel">
  <div class="metrics-controls"><label>数据来源<select v-model="source" :disabled="loading" @change="reload"><option value="business">真实业务</option><option value="evaluation">评测样例</option><option value="all">全部数据</option></select></label><div><button v-for="n in [7,30,90]" :key="n" :class="{active:days===n}" :disabled="loading" @click="days=n;reload()">近 {{ n }} 天</button></div></div>
  <ContentState v-if="loading" kind="loading" title="正在读取运行指标" /><ContentState v-else-if="error" kind="error" title="指标加载失败" :description="error" @retry="reload" />
  <template v-else-if="report"><div class="metric-grid"><article v-for="item in cards" :key="item.label"><small>{{ item.label }}</small><strong>{{ item.value }}</strong><p>{{ item.note }}</p></article></div>
   <article class="metrics-chart"><h2>每日运行与失败</h2><AdminTrendChart title="每日 Agent 运行与失败数量" :rows="report.daily.map((r:any)=>({date:r.date,values:[r.count,r.failed]}))" :series="[{name:'运行数',color:'#11110f'},{name:'失败数',color:'#c75b49'}]" /></article>
   <p class="metrics-scope">{{ report.from }} — {{ report.to }}。{{ report.scope }}</p><p class="metrics-scope">使用量采样 {{ report.sampledRuns }} 次，其中 {{ report.runsWithMetrics }} 次有指标，{{ report.completeUsageRuns }} 次 Token 数据完整。旧运行缺失的指标保留为空。</p>
  </template>
 <AnswerFeedbackReport ref="feedbackReport" :source="source" />
 </section>
</template>
<script setup lang="ts">
import { computed,onMounted,onUnmounted,ref } from 'vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import ContentState from './ContentState.vue'
import AdminTrendChart from './AdminTrendChart.vue'
import AnswerFeedbackReport from './AnswerFeedbackReport.vue'
const feedbackReport=ref<InstanceType<typeof AnswerFeedbackReport>>()
const days=ref(7),source=ref('business'),report=ref<any>(),loading=ref(false),error=ref(''),gate=latestRequest();let disposed=false
const number=(n:number)=>new Intl.NumberFormat('zh-CN').format(n)
const seconds=(n:number|null)=>n===null?'—':`${(n/1000).toFixed(2)} 秒`
const cards=computed(()=>{const r=report.value;if(!r)return [];return [
 {label:'运行数量',value:number(r.totalRuns),note:`其中 ${r.finishedRuns} 次已结束`},
 {label:'完成成功率',value:r.successRate===null?'—':`${r.successRate.toFixed(2)}%`,note:'取消、过期计入未成功；进行中不计'},
 {label:'活跃时长 P50 / P95',value:`${seconds(r.activeP50Ms)} / ${seconds(r.activeP95Ms)}`,note:`${r.latencySamples} 个已结束样本，排除审批等待`},
 {label:'模型调用 / 失败',value:`${number(r.llmCalls)} / ${number(r.failedLlmCalls)}`,note:'Agent 图内调用，不含后台记忆处理'},
 {label:'已记录输入 Token',value:number(r.measuredInputTokens),note:'供应商返回的使用量，缺失部分不估算'},
 {label:'已记录输出 Token',value:number(r.measuredOutputTokens),note:'使用量统计，不代表费用'}]})
async function reload(){void feedbackReport.value?.load();const run=gate.begin();loading.value=true;error.value='';try{const result:any=await request.get('/admin/agent-metrics',{params:{days:days.value,source:source.value},signal:run.signal});if(run.isCurrent() && !disposed)report.value=result.data}catch(e){if(run.isCurrent() && !disposed)error.value=e instanceof Error?e.message:'请求失败'}finally{if(run.isCurrent() && !disposed)loading.value=false}}
defineExpose({reload});onMounted(reload);onUnmounted(()=>{disposed=true;gate.cancel()})
</script>
<style scoped>
.metrics-controls{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:22px}.metrics-controls label{display:flex;align-items:center;gap:10px;font-size:13px}.metrics-controls select,.metrics-controls button{font:inherit;background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:99px;padding:10px 14px}.metrics-controls button{cursor:pointer;margin-left:6px;font-size:12px}.metrics-controls button.active{background:var(--studio-lime);border-color:var(--ej-ink)}.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.metric-grid article,.metrics-chart{background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:18px;padding:22px}.metric-grid small,.metric-grid p,.metrics-scope{color:var(--ej-muted);font-size:12px;line-height:1.8}.metric-grid strong{display:block;margin:15px 0;font-size:24px;overflow-wrap:anywhere}.metric-grid p{margin:0}.metrics-chart{margin-top:22px}.metrics-chart h2{font-size:17px}.metrics-scope{margin:16px 0}@media(max-width:1000px){.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.metric-grid{grid-template-columns:1fr}}
</style>
