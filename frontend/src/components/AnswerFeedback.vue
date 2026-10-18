<template>
  <div class="answer-feedback" aria-label="回答反馈">
    <button type="button" :disabled="busy" :aria-pressed="rating==='helpful'" @click="submit(rating==='helpful'?'':'helpful')">{{ rating==='helpful'?'✓ 有帮助':'有帮助' }}</button>
    <button type="button" :disabled="busy" :aria-pressed="rating==='problem'" :aria-expanded="open" @click="open=!open">有问题</button>
    <span role="status">{{ status }}</span>
    <form v-if="open" class="answer-feedback-form" @submit.prevent="submit('problem')">
      <label class="feedback-reason">问题类型<AppSelect v-model="reason" :disabled="busy"><AppSelectOption value="irrelevant">答非所问</AppSelectOption><AppSelectOption value="incorrect">事实或推理错误</AppSelectOption><AppSelectOption value="citation">引用有误</AppSelectOption><AppSelectOption value="incomplete">回答不完整</AppSelectOption><AppSelectOption value="other">其他</AppSelectOption></AppSelect></label>
      <label class="feedback-comment">补充说明 <small>选填 · 最多500字</small><textarea v-model="comment" :disabled="busy" maxlength="500" rows="3" placeholder="哪里需要改进？可以指出具体内容。" /></label>
      <div class="feedback-actions"><button class="feedback-submit" :disabled="busy">{{ busy?'正在提交…':'提交反馈' }}</button><button type="button" :disabled="busy" @click="open=false">取消</button></div>
    </form>
  </div>
</template>
<script setup lang="ts">
import {ref,watch} from 'vue';import request from '@/utils/request'
const props=defineProps<{runId:string}>(),rating=ref(''),reason=ref('incorrect'),comment=ref(''),busy=ref(false),open=ref(false),status=ref('');let generation=0
watch(()=>props.runId,async id=>{const turn=++generation;rating.value='';try{const r:any=await request.get(`/agent/runs/${id}/feedback`);if(turn===generation && r.data){rating.value=r.data.rating;reason.value=r.data.reason||'incorrect';comment.value=r.data.comment||''}}catch{}},{immediate:true})
async function submit(value:string){if(busy.value)return;const id=props.runId,turn=generation;busy.value=true;status.value='';try{await request.put(`/agent/runs/${id}/feedback`,{rating:value,reason:reason.value,comment:comment.value});if(turn===generation){rating.value=value;open.value=false;status.value=value?'感谢反馈，已记录':'已撤销反馈'}}catch(e){if(turn===generation)status.value=e instanceof Error?e.message:'提交失败，请重试'}finally{busy.value=false}}
</script>
<style scoped>
.answer-feedback{margin-top:16px;font-size:12px;color:var(--ej-muted);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.answer-feedback button{font:inherit;color:var(--ej-ink);border:1px solid var(--ej-line);border-radius:99px;padding:7px 13px;background:var(--ej-surface);cursor:pointer;transition:background .16s,border-color .16s}
.answer-feedback button:hover:enabled{border-color:var(--ej-ink);background:var(--studio-lime-soft)}.answer-feedback button[aria-pressed=true]{background:var(--studio-lime);border-color:var(--ej-ink)}.answer-feedback button:disabled{opacity:.5;cursor:not-allowed}
.answer-feedback-form{flex-basis:100%;min-width:0;display:grid;gap:16px;padding:18px;background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:16px}
.feedback-reason{display:grid;grid-template-columns:auto minmax(0,260px);align-items:center;gap:12px;color:var(--ej-ink);justify-content:start}.feedback-comment{display:block;color:var(--ej-ink)}.feedback-comment small{margin-left:8px;color:var(--ej-muted);font-size:11px}
.answer-feedback textarea{display:block;box-sizing:border-box;width:100%;margin-top:8px;resize:vertical;min-height:86px;background:var(--ej-canvas);color:var(--ej-ink);border:1px solid var(--ej-line);border-radius:10px;padding:10px 12px;font:inherit;line-height:1.7}.answer-feedback textarea:focus{outline:2px solid var(--studio-lime);outline-offset:1px}.feedback-actions{display:flex;gap:8px}.answer-feedback .feedback-submit{background:var(--ej-ink);color:var(--ej-surface);border-color:var(--ej-ink)}.answer-feedback .feedback-submit:hover:enabled{background:var(--studio-lime);color:var(--ej-ink)}
@media(max-width:600px){.answer-feedback-form{padding:14px}.feedback-reason{grid-template-columns:minmax(0,1fr);gap:7px}.feedback-comment small{display:block;margin:4px 0 0}}
</style>
