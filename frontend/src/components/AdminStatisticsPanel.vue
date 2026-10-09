<template>
  <section class="statistics-panel" aria-label="社区数据统计">
    <div class="statistics-heading"><div><h2>社区数据</h2><p>以下图表与导出按所选来源筛选；上方管理概览为全部记录。</p></div><div class="statistics-controls"><select v-model="source" aria-label="统计数据来源" :disabled="exporting" @change="reload"><option value="business">真实业务</option><option value="evaluation">评测样例</option><option value="all">全部数据</option></select><div class="statistics-range" role="group" aria-label="统计日期范围"><button v-for="value in [7,30,90]" :key="value" :aria-pressed="days===value" :class="{selected:days===value}" :disabled="exporting" @click="selectRange(value)">近 {{ value }} 天</button></div><button class="statistics-export" :disabled="loading || exporting || !report || !!error" @click="download"><Download />{{ exporting?'正在导出…':'导出 Excel' }}</button></div></div>
    <ContentState v-if="loading" kind="loading" title="正在统计社区数据" />
    <ContentState v-else-if="error" kind="error" title="统计暂时无法加载" :description="error" @retry="reload" />
    <template v-else-if="report">
      <div class="statistics-period"><span>{{ report.from }} — {{ report.to }} · 含今天</span><span>新增用户 <strong>{{ report.periodNewUsers }}</strong></span><span>首次发布 <strong>{{ report.periodNewArticles }}</strong></span><span>有效阅读 <strong>{{ readingDuration(report.periodReadingSeconds) }}</strong></span><span>阅读用户 <strong>{{ report.periodReadingUsers }}</strong></span></div>
      <div class="statistics-charts">
        <article class="statistics-card"><header><h3>用户与文章趋势</h3><span>每日数量</span></header><AdminTrendChart title="每日新增用户与首次发布文章" :rows="growthRows" :series="[{name:'新增用户',color:'#11110f'},{name:'首次发布',color:'#c75b49'}]" /><p class="statistics-note">按注册日期和首次发布时间统计，排除已删除文章。</p></article>
        <article class="statistics-card"><header><h3>有效阅读趋势</h3><span>分钟</span></header><AdminTrendChart title="每日有效阅读分钟数" :rows="readingRows" :series="[{name:'有效阅读',color:'#648333'}]" bars unit="分钟" /><p class="statistics-note">实际每日计时记录，不包含管理员校正的成长时长。</p></article>
        <article class="statistics-card"><header><h3>文章状态</h3><span>当前 {{ articleTotal }} 篇</span></header><div v-for="(item,i) in report.articles" :key="item.name" class="distribution-row"><div><span><i :style="{background:colors[i%colors.length]}"></i>{{ item.name }}</span><strong>{{ item.count }}<small> · {{ percent(item.count,articleTotal) }}%</small></strong></div><div class="distribution-track"><span :style="{width:`${percent(item.count,articleTotal)}%`,background:colors[i%colors.length]}"></span></div></div><p class="statistics-note">未公开、已发布与已下架互斥；不统计已删除文章。</p></article>
        <article class="statistics-card"><header><h3>阅读等级</h3><span>当前 {{ userTotal }} 人</span></header><div v-for="item in report.levels" :key="item.name" class="distribution-row"><div><span>{{ item.name }}</span><strong>{{ item.count }}<small> · {{ percent(item.count,userTotal) }}%</small></strong></div><div class="distribution-track"><span :style="{width:`${percent(item.count,userTotal)}%`,background:'#a0bc61'}"></span></div></div><p class="statistics-note">所选来源内的账号，含禁用账号；无阅读记录计入 L0。</p></article>
      </div>
      <p class="statistics-stamp">生成于 {{ report.generatedAt.replace('T',' ').slice(0,19) }} · 北京时间。Excel 含统计说明及四个工作表。</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed,onMounted,onUnmounted,ref } from 'vue'
import { Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ContentState from './ContentState.vue'
import AdminTrendChart from './AdminTrendChart.vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import { readingDuration } from '@/utils/readingGrowth'
import { spreadsheetBlob,type StatisticsReport } from '@/utils/statistics'
const days=ref(30),source=ref<'business'|'evaluation'|'all'>('business'),report=ref<StatisticsReport>(),loading=ref(false),exporting=ref(false),error=ref(''),gate=latestRequest()
let disposed=false
const colors=['#a69a84','#a0bc61','#e29a86']
const growthRows=computed(()=>report.value?.daily.map(r=>({date:r.date,values:[r.newUsers,r.newArticles]})) || [])
const readingRows=computed(()=>report.value?.daily.map(r=>({date:r.date,values:[r.readingMillis/60000]})) || [])
const articleTotal=computed(()=>report.value?.articles.reduce((sum,r)=>sum+r.count,0) || 0)
const userTotal=computed(()=>report.value?.levels.reduce((sum,r)=>sum+r.count,0) || 0)
const percent=(count:number,total:number)=>total===0?0:Math.round(count/total*1000)/10
const message=(e:unknown)=>e instanceof Error?e.message:'请求失败，请重试'
async function reload(){
  const run=gate.begin();loading.value=true;error.value=''
  try{const result:any=await request.get('/admin/statistics',{params:{days:days.value,source:source.value},signal:run.signal});if(run.isCurrent() && !disposed)report.value=result.data}
  catch(e){if(run.isCurrent() && !disposed)error.value=message(e)}finally{if(run.isCurrent() && !disposed)loading.value=false}
}
function selectRange(value:number){if(days.value===value)return;days.value=value;void reload()}
async function download(){
  if(!report.value || exporting.value)return
  exporting.value=true
  const range=days.value
  try{
    const result:unknown=await request.get('/admin/statistics/export',{params:{days:range,source:source.value},responseType:'blob',timeout:30000})
    const blob=await spreadsheetBlob(result);if(disposed)return
    const url=URL.createObjectURL(blob),link=document.createElement('a')
    link.href=url;link.download=`EasyJob统计_${{business:'真实业务',evaluation:'评测样例',all:'全部数据'}[source.value]}_近${range}天.xlsx`;document.body.appendChild(link);link.click();link.remove()
    setTimeout(()=>URL.revokeObjectURL(url),1000);ElMessage.success('Excel 已导出')
  }catch(e){if(!disposed)ElMessage.error(message(e))}finally{if(!disposed)exporting.value=false}
}
defineExpose({reload})
onMounted(reload);onUnmounted(()=>{disposed=true;gate.cancel()})
</script>

<style scoped>
.statistics-panel{margin-top:30px}.statistics-heading{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:20px}.statistics-heading h2{font-size:19px;margin:0 0 8px}.statistics-heading p{font-size:12px;color:var(--ej-muted);margin:0}.statistics-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.statistics-controls>select{font:inherit;font-size:12px;padding:10px 12px;border:1px solid var(--ej-line);border-radius:99px;background:var(--ej-surface);color:var(--ej-ink);max-width:100%}.statistics-controls>select:focus-visible{outline:2px solid var(--ej-ink);outline-offset:3px}.statistics-controls>select:disabled{opacity:.5}.statistics-range{display:flex;padding:4px;background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:99px;gap:2px}.statistics-range button{background:none;border:1px solid transparent;border-radius:99px;padding:8px 12px;font:inherit;font-size:11px;cursor:pointer;white-space:nowrap}.statistics-range button.selected{background:var(--studio-lime);border-color:var(--ej-ink)}.statistics-export{display:flex;gap:8px;align-items:center;border:1px solid var(--ej-ink);border-radius:99px;padding:11px 16px;background:var(--ej-ink);color:var(--ej-surface);font:inherit;font-size:12px;cursor:pointer;white-space:nowrap}.statistics-export svg{width:15px;height:15px}.statistics-controls button:disabled{opacity:.5;cursor:not-allowed}.statistics-period{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--ej-muted);margin-bottom:16px;line-height:1.8}.statistics-period strong{color:var(--ej-ink);margin-left:4px}.statistics-charts{display:grid;grid-template-columns:1fr 1fr;gap:20px}.statistics-card{min-width:0;border:1px solid var(--ej-line);border-radius:18px;padding:22px;background:var(--ej-surface);transition:border-color .18s}.statistics-card:hover{border-color:var(--ej-ink)}.statistics-card header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.statistics-card h3{font-size:15px;margin:0}.statistics-card header>span{font-size:11px;color:var(--ej-muted)}.statistics-note,.statistics-stamp{font-size:11px;color:var(--ej-muted);line-height:1.8}.statistics-note{margin:14px 0 0}.statistics-stamp{margin-top:16px}.distribution-row{margin:16px 0}.distribution-row>div:first-child{display:flex;justify-content:space-between;font-size:12px;gap:12px;align-items:center;margin-bottom:8px}.distribution-row i{display:inline-block;width:8px;height:8px;margin-right:8px;border-radius:50%}.distribution-row small{font-weight:400;color:var(--ej-muted);font-size:11px}.distribution-track{height:8px;background:var(--ej-canvas);border-radius:99px;overflow:hidden}.distribution-track span{display:block;height:100%;border-radius:99px;transition:width .3s ease}
@media(max-width:1000px){.statistics-heading{align-items:flex-start;flex-direction:column}.statistics-controls{width:100%;justify-content:space-between}}
@media(max-width:760px){.statistics-charts{grid-template-columns:1fr}.statistics-card{padding:18px}.statistics-period{gap:10px}.statistics-export{padding:10px 12px}}
@media(prefers-reduced-motion:reduce){.statistics-card,.distribution-track span{transition:none}}
</style>
