<template>
  <span v-if="!own" class="relationship-control" @click.stop>
    <button type="button" class="follow-btn" :class="{following:value?.isFollowing}" :disabled="busy" @click="primary">{{ busy ? '处理中…' : relationshipLabel(value) }}</button>
  </span>
</template>
<script setup lang="ts">
import {computed,watch} from 'vue'
import {ref} from 'vue'
import {useRouter} from 'vue-router'
import {ElMessage,ElMessageBox} from 'element-plus'
import {relationships,queueRelationship,relationshipLabel,changeFollow} from '@/utils/social'
const props=defineProps<{userId:string|number}>()
const emit=defineEmits<{changed:[value:any]}>()
const router=useRouter(),busy=ref(false)
const id=computed(()=>String(props.userId)),own=computed(()=>id.value===localStorage.getItem('userId'))
const value=computed(()=>relationships[id.value])
watch(id,id=>queueRelationship(id),{immediate:true})
async function apply(following:boolean,target=id.value){busy.value=true;try{const changed=await changeFollow(target,following);if(id.value===target)emit('changed',changed)}catch(e){ElMessage.error(e instanceof Error?e.message:'操作失败')}finally{busy.value=false}}
async function primary(){
  if(!localStorage.getItem('token')){router.push({path:'/',query:{login:'true',redirect:router.currentRoute.value.fullPath}});return}
  if(value.value?.isBlockedByMe){ElMessage.info('请在消息设置的黑名单中解除拉黑');return}
  if(value.value?.isFollowing){await unfollow();return}
  await apply(true)
}
async function unfollow(){const target=id.value;try{await ElMessageBox.confirm('确定取消关注该用户吗？已有聊天记录会保留。','取消关注',{confirmButtonText:'确定',cancelButtonText:'取消'});await apply(false,target)}catch{/* cancelled */}}
</script>
<style scoped>
.relationship-control{display:inline-flex;align-items:center}.follow-btn{border:1px solid var(--ej-ink);border-radius:999px;padding:8px 16px;background:var(--studio-lime,#c5ff45);color:var(--ej-ink);font:inherit;white-space:nowrap;cursor:pointer}.follow-btn.following{background:var(--ej-surface)}.follow-btn:disabled{opacity:.6;cursor:wait}
</style>
