<template>
  <el-dialog v-model="visible" class="admin-user-dialog" title="编辑用户" width="min(680px, 94vw)" align-center :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" :before-close="close">
    <ContentState v-if="loading" kind="loading" title="正在加载用户资料" />
    <ContentState v-else-if="!original" kind="error" title="暂时无法加载资料" :description="error" @retry="load" />
    <form v-else id="admin-user-form" class="user-editor" @submit.prevent="save">
      <p class="user-editor-id">用户 ID {{ original.userId }}<span v-if="ownAccount"> · 当前账号</span></p>
      <fieldset :disabled="saving">
        <label>昵称<input v-model="form.nickName" required maxlength="20" autocomplete="off" /></label>
        <label>个人简介<textarea v-model="form.personIntroduction" rows="3" maxlength="200" placeholder="可留空" /></label>
        <div class="user-editor-grid">
          <label>角色<select v-model.number="form.role" :disabled="ownAccount"><option :value="1">普通用户</option><option :value="2">管理员</option><option :value="3">审核员</option><option :value="4">运营员</option></select></label>
          <label>账号状态<select v-model.number="form.status" :disabled="ownAccount"><option :value="1">正常</option><option :value="0">禁用</option></select></label>
        </div>
        <p class="user-editor-note">{{ ownAccount ? '当前账号的管理员身份和启用状态受保护。' : '修改角色或状态后，用户需重新登录；禁用后无法继续使用账号。' }}</p>
        <section class="user-growth-editor">
          <div><strong>阅读成长</strong><span class="user-editor-level">L{{ original.readingLevel }}</span><span>{{ readingDuration(original.readingSeconds) }}</span></div>
          <label class="user-editor-check"><input v-model="correctReading" type="checkbox" />校正累计有效阅读时长</label>
          <template v-if="correctReading">
            <div class="user-editor-grid time-grid"><label>小时<input v-model.number="hours" type="number" min="0" max="87600" step="1" required /></label><label>分钟<input v-model.number="minutes" type="number" min="0" max="59" step="1" required /></label><label>秒<input v-model.number="seconds" type="number" min="0" max="59" step="1" required /></label></div>
            <p class="user-editor-note">校正后为 L{{ correctedLevel }}，{{ readingDuration(correctedSeconds) }}。等级按校正后的时长重新计算，可升可降；当前阅读计时需重新开始，历史每日阅读统计保留。</p>
          </template>
        </section>
        <label>修改原因<textarea v-model="reason" rows="2" maxlength="300" required placeholder="说明本次修改的原因，将保存在操作日志中" /></label>
      </fieldset>
      <p v-if="error" role="alert" class="user-editor-error">{{ error }}</p>
      <button v-if="error" type="button" class="user-editor-reload" :disabled="saving" @click="load">重新加载最新资料（会重置表单）</button>
    </form>
    <template #footer><div class="user-editor-footer"><button type="button" :disabled="saving" @click="close()">取消</button><button v-if="original" class="primary" type="submit" form="admin-user-form" :disabled="saving || loading">{{ saving ? '正在保存…' : '保存修改' }}</button></div></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ContentState from './ContentState.vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import { readingDuration } from '@/utils/readingGrowth'

type Profile = { nickName:string;personIntroduction:string|null;role:number;status:number }
type Detail = Profile & { userId:string;readingMillis:string;readingSeconds:number;readingLevel:number;rules:{level:number;minSeconds:number}[] }
const visible=defineModel<boolean>({default:false})
const props=defineProps<{userId:string;operatorId?:string}>()
const emit=defineEmits<{changed:[]}>()
const original=ref<Detail>(),form=reactive<Profile>({nickName:'',personIntroduction:'',role:1,status:1})
const loading=ref(false),saving=ref(false),error=ref(''),reason=ref(''),correctReading=ref(false)
const hours=ref(0),minutes=ref(0),seconds=ref(0),gate=latestRequest()
const ownAccount=computed(()=>props.userId===props.operatorId)
const correctedSeconds=computed(()=>Number(hours.value)*3600+Number(minutes.value)*60+Number(seconds.value))
const correctedLevel=computed(()=>Math.max(0,...(original.value?.rules || []).filter(r=>correctedSeconds.value>=r.minSeconds).map(r=>r.level)))
const message=(e:unknown)=>e instanceof Error?e.message:'操作失败，请重试'
async function load(){
  const run=gate.begin();loading.value=true;original.value=undefined;error.value=''
  try{
    const result:any=await request.get(`/admin/users/${props.userId}`,{signal:run.signal})
    if(!run.isCurrent())return
    original.value=result.data;Object.assign(form,result.data)
    hours.value=Math.floor(result.data.readingSeconds/3600);minutes.value=Math.floor(result.data.readingSeconds%3600/60);seconds.value=result.data.readingSeconds%60
    reason.value='';correctReading.value=false
  }catch(e){if(run.isCurrent())error.value=message(e)}finally{if(run.isCurrent())loading.value=false}
}
function close(done?:()=>void){if(saving.value)return;gate.cancel();visible.value=false;done?.()}
async function save(){
  if(!original.value || saving.value)return
  if(!form.nickName.trim() || !reason.value.trim()){error.value='请填写昵称和修改原因';return}
  if(correctReading.value && (![hours.value,minutes.value,seconds.value].every(v=>Number.isInteger(v) && v>=0) || minutes.value>59 || seconds.value>59 || correctedSeconds.value>315360000)){error.value='请填写有效的阅读时长';return}
  const data=original.value;saving.value=true;error.value=''
  try{
    await request.put(`/admin/users/${data.userId}`,{
      expectedProfile:{nickName:data.nickName,personIntroduction:data.personIntroduction,role:data.role,status:data.status},
      nickName:form.nickName.trim(),personIntroduction:form.personIntroduction || null,role:form.role,status:form.status,
      readingSeconds:correctReading.value?correctedSeconds.value:null,expectedReadingMillis:correctReading.value?data.readingMillis:null,reason:reason.value.trim()
    })
    ElMessage.success('用户资料已更新');visible.value=false;emit('changed')
  }catch(e){error.value=message(e)}finally{saving.value=false}
}
watch(()=>[visible.value,props.userId],()=>{if(visible.value && props.userId)void load();else gate.cancel()},{immediate:true})
onUnmounted(()=>gate.cancel())
</script>

<style scoped>
.user-editor{color:var(--ej-ink)}.user-editor-id,.user-editor-note{color:var(--ej-muted);font-size:12px;line-height:1.7;margin:0 0 16px}.user-editor fieldset{border:0;padding:0;margin:0;min-width:0}.user-editor label{display:flex;flex-direction:column;gap:8px;font-size:13px;margin-bottom:18px}.user-editor input:not([type=checkbox]),.user-editor select,.user-editor textarea{box-sizing:border-box;width:100%;border:1px solid var(--ej-line);border-radius:10px;background:var(--ej-canvas);padding:11px 12px;color:inherit;font:inherit;resize:vertical}.user-editor input:focus,.user-editor select:focus,.user-editor textarea:focus{outline:2px solid var(--studio-lime);outline-offset:1px}.user-editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.time-grid{grid-template-columns:repeat(3,1fr)}.user-growth-editor{border:1px solid var(--ej-line);border-radius:14px;padding:16px;margin-bottom:20px}.user-growth-editor>div:first-child{display:flex;align-items:center;gap:12px;font-size:13px;margin-bottom:16px}.user-editor-level{background:var(--studio-lime-soft);padding:4px 8px;border-radius:99px}.user-editor .user-editor-check{flex-direction:row;align-items:center;gap:10px}.user-editor-check input{accent-color:var(--ej-ink)}.user-growth-editor .user-editor-note{margin-bottom:0}.user-editor-error{font-size:13px;color:#b44a36;line-height:1.7}.user-editor-reload{border:0;background:none;color:inherit;text-decoration:underline;font-size:12px;cursor:pointer}.user-editor-footer{display:flex;justify-content:flex-end;gap:12px}.user-editor-footer button{padding:10px 20px;border:1px solid var(--ej-ink);border-radius:99px;background:var(--ej-surface);color:var(--ej-ink);cursor:pointer}.user-editor-footer .primary{background:var(--ej-ink);color:var(--ej-surface)}.user-editor button:disabled,.user-editor-footer button:disabled,.user-editor select:disabled{opacity:.5;cursor:not-allowed}
</style>

<style>
html .el-dialog.admin-user-dialog{display:flex;flex-direction:column;max-height:calc(100dvh - 40px);margin:20px auto;border:1.5px solid var(--ej-ink);border-radius:22px;background:var(--ej-surface);box-shadow:6px 6px 0 #11110f26}.admin-user-dialog .el-dialog__body{overflow-y:auto;min-height:0;padding:12px 4px}.admin-user-dialog .el-dialog__header,.admin-user-dialog .el-dialog__footer{flex-shrink:0}.admin-user-dialog .el-dialog__footer{border-top:1px solid var(--ej-hairline);padding-top:16px}
</style>
