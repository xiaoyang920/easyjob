<template>
  <div class="trend-chart">
    <svg viewBox="0 0 660 215" role="group" :aria-label="title">
      <g v-for="tick in ticks" :key="tick.y"><line x1="48" x2="632" :y1="tick.y" :y2="tick.y" class="chart-grid" /><text x="39" :y="tick.y+4" text-anchor="end" class="chart-label">{{ format(tick.value) }}</text></g>
      <template v-for="(item,s) in series" :key="item.name">
        <path v-if="!bars" :d="paths[s]" fill="none" :stroke="item.color" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        <rect v-for="(point,i) in bars?points[s]:[]" :key="i" :x="point.x-barWidth/2" :y="point.y" :width="barWidth" :height="178-point.y" rx="2" :fill="item.color" opacity=".85" />
        <circle v-if="points[s]?.[active]" :cx="points[s]![active]!.x" :cy="points[s]![active]!.y" r="4" :fill="item.color" stroke="var(--ej-surface)" stroke-width="2" />
      </template>
      <line v-if="rows.length" :x1="points[0]?.[active]?.x" :x2="points[0]?.[active]?.x" y1="32" y2="178" class="chart-cursor" />
      <text v-for="i in labels" :key="i" :x="points[0]?.[i]?.x" y="205" :text-anchor="i===0?'start':i===rows.length-1?'end':'middle'" class="chart-label">{{ rows[i]?.date.slice(5) }}</text>
      <rect v-for="(row,i) in rows" :key="row.date" :x="Math.max(48,(points[0]?.[i]?.x || 48)-hitWidth/2)" y="26" :width="hitWidth" height="160" fill="transparent" tabindex="0" role="button" :aria-label="rowLabel(row)" @pointerenter="active=i" @focus="active=i" @keydown.left.prevent="active=Math.max(0,active-1)" @keydown.right.prevent="active=Math.min(rows.length-1,active+1)" />
    </svg>
    <div v-if="rows[active]" class="chart-readout" aria-live="polite"><span>{{ rows[active]!.date }}</span><span v-for="(item,s) in series" :key="item.name"><i :style="{background:item.color}"></i>{{ item.name }} <strong>{{ format(rows[active]!.values[s] || 0) }}</strong>{{ unit }}</span></div>
    <details class="chart-data"><summary>查看每日数据</summary><div><table><thead><tr><th>日期</th><th v-for="item in series" :key="item.name">{{ item.name }}{{ unit?`（${unit}）`:'' }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.date"><td>{{ row.date }}</td><td v-for="(value,s) in row.values" :key="s">{{ format(value) }}</td></tr></tbody></table></div></details>
  </div>
</template>

<script setup lang="ts">
import { computed,ref,watch } from 'vue'
import { chartCeiling,chartPoints } from '@/utils/statistics'
type Row={date:string;values:number[]}
const props=defineProps<{title:string;rows:Row[];series:{name:string;color:string}[];bars?:boolean;unit?:string}>()
const active=ref(0)
watch(()=>props.rows,rows=>{active.value=Math.max(0,rows.length-1)},{immediate:true})
const ceiling=computed(()=>chartCeiling(props.rows.flatMap(r=>r.values)))
const points=computed(()=>props.series.map((_,s)=>chartPoints(props.rows.map(r=>r.values[s] || 0),ceiling.value)))
const paths=computed(()=>points.value.map(list=>list.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ')))
const ticks=computed(()=>Array.from({length:5},(_,i)=>({y:178-i*36.5,value:ceiling.value*i/4})))
const labels=computed(()=>[...new Set([0,Math.floor((props.rows.length-1)/2),props.rows.length-1])].filter(i=>i>=0))
const barWidth=computed(()=>Math.min(16,584/Math.max(1,props.rows.length)*.7))
const hitWidth=computed(()=>584/Math.max(1,props.rows.length-1))
const format=(n:number)=>n.toLocaleString('zh-CN',{maximumFractionDigits:2})
const rowLabel=(row:Row)=>`${row.date}，${props.series.map((s,i)=>`${s.name}${format(row.values[i] || 0)}${props.unit || ''}`).join('，')}`
</script>

<style scoped>
.trend-chart svg{display:block;width:100%;height:auto;overflow:visible}.chart-grid{stroke:var(--ej-hairline);stroke-dasharray:3 5}.chart-label{fill:var(--ej-muted);font-size:11px;font-family:var(--ej-font)}.chart-cursor{stroke:var(--ej-line);stroke-dasharray:4 4;pointer-events:none}.trend-chart rect[tabindex]:focus{outline:none;stroke:var(--ej-ink);stroke-width:1;stroke-dasharray:3 4}.chart-readout{display:flex;gap:12px;flex-wrap:wrap;min-height:20px;font-size:11px;color:var(--ej-muted);margin:6px 0}.chart-readout>span{display:inline-flex;align-items:center;gap:5px}.chart-readout i{display:inline-block;width:7px;height:7px;border-radius:50%}.chart-readout strong{color:var(--ej-ink)}.chart-data{margin-top:16px;border-top:1px solid var(--ej-hairline);padding-top:12px;font-size:11px}.chart-data summary{cursor:pointer;color:var(--ej-muted)}.chart-data>div{overflow:auto;max-height:240px;margin-top:12px}.chart-data table{border-collapse:collapse;width:100%;font-size:11px}.chart-data th,.chart-data td{padding:8px;text-align:right;border-bottom:1px solid var(--ej-hairline);white-space:nowrap}.chart-data th:first-child,.chart-data td:first-child{text-align:left}
</style>
