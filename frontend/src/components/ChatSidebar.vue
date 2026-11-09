<template>
  <div class="social-sidebar">
    <div class="social-heading"><h2>消息与朋友</h2><button type="button" @click="settingsOpen=!settingsOpen">设置</button></div>
    <div v-if="settingsOpen" class="social-settings">
      <label><input type="checkbox" :checked="allowRequests" :disabled="busy" @change="savePrivacy(($event.target as HTMLInputElement).checked)">接收陌生人的消息请求</label>
      <button type="button" @click="contactKind=contactKind==='blocked'?'friends':'blocked';tab='friends';loadContacts(true)">{{contactKind==='blocked'?'返回朋友':'管理黑名单'}}</button>
    </div>
    <nav class="social-tabs" aria-label="消息分类"><button v-for="item in tabs" :key="item.key" type="button" :class="{active:tab===item.key}" @click="chooseTab(item.key)">{{item.label}}<span v-if="item.key==='messages' && unread">{{unread}}</span><span v-if="item.key==='requests' && requests.length">{{requests.length}}</span></button></nav>
    <input v-model="search" class="social-search" :placeholder="tab==='friends'?'搜索昵称或备注':'搜索会话'" aria-label="搜索联系人或会话">
    <p v-if="error" role="alert">{{error}} <button @click="refresh">重试</button></p>
    <div class="social-items">
      <p v-if="loading || (tab==='messages' && conversationsLoading)" class="social-empty">加载中…</p>
      <template v-if="tab==='friends'">
        <p v-if="!loading && !contacts.length" class="social-empty">{{contactKind==='blocked'?'黑名单为空':'互相关注后会出现在这里'}}<router-link v-if="contactKind!=='blocked'" :to="`/followers-following?tab=followers&userId=${me}`">查看粉丝，回关成为朋友</router-link></p>
        <div v-for="person in contacts" :key="person.userId" class="contact-item">
          <button class="social-person" @click="$emit('target',String(person.userId))" :disabled="contactKind==='blocked'"><img :src="avatarUrl(person.avatar,person.nickName)" alt=""><span><strong>{{person.remark||person.nickName}}</strong><small v-if="person.remark">{{person.nickName}}</small><small v-else>{{contactKind==='blocked'?'已拉黑':'互相关注'}}</small></span></button>
          <button v-if="contactKind==='blocked'" @click="unblock(person.userId)">解除拉黑</button><button v-else @click="$router.push(`/user-space/${person.userId}`)">空间</button>
        </div>
        <button v-if="contacts.length<contactTotal" class="more" :disabled="loading" @click="loadContacts(false)">加载更多朋友</button>
      </template>
      <template v-else>
        <p v-if="!loading && !visible.length" class="social-empty">{{tab==='requests'?'暂无消息请求':'暂无会话'}}<button v-if="tab==='messages'" @click="chooseTab('friends')">找朋友聊聊</button></p>
        <button v-for="conv in visible" :key="conv.conversationId" class="social-conversation" :class="{selected:currentId===conv.conversationId}" @click="$emit('select',conv)">
          <img :src="avatarUrl(conv.otherUserAvatar,conv.otherUserName)" alt=""><span class="social-preview"><strong>{{conv.remark||conv.otherUserName}}<i v-if="conv.isTop">置顶</i><i v-if="conv.isMuted">免打扰</i></strong><small>{{conv.lastMessage||'开始聊天'}}</small></span><span v-if="tab==='requests' ? conv.requestUnseen : conv.unreadCount" class="social-unread">{{tab==='requests'?'新':Math.min(99,conv.unreadCount)}}</span>
        </button>
      </template>
    </div>
  </div>
</template>
<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import {useRoute} from 'vue-router'
import {ElMessage} from 'element-plus'
import request from '@/utils/request'
import {avatarUrl} from '@/utils/avatar'
import {eventBus} from '@/utils/eventBus'
const props=defineProps<{conversations:any[];conversationsLoading:boolean;currentId?:string;refreshKey:number}>()
defineEmits<{select:[conv:any];target:[id:string]}>()
const route=useRoute(),me=localStorage.getItem('userId')||''
const tab=ref(['friends','requests'].includes(String(route.query.tab))?String(route.query.tab):'messages')
const tabs=computed(()=>[{key:'messages',label:'消息'},...(featuresEnabled.value?[{key:'friends',label:'朋友'},{key:'requests',label:'消息请求'}]:[])])
const search=ref(''),requests=ref<any[]>([]),contacts=ref<any[]>([]),contactTotal=ref(0),contactKind=ref('friends'),page=ref(0)
const settingsOpen=ref(false),allowRequests=ref(true),busy=ref(false),loading=ref(false),error=ref('')
const featuresEnabled=ref(true)
let generation=0,timer:ReturnType<typeof setTimeout>|undefined
const unread=computed(()=>props.conversations.filter(c=>!c.isMuted).reduce((n,c)=>n+(c.unreadCount||0),0))
const visible=computed(()=>(tab.value==='requests'?requests.value:props.conversations).filter(c=>[c.remark,c.otherUserName,c.lastMessage].some(v=>String(v||'').includes(search.value))))
async function loadContacts(reset=true){
  const ticket=++generation;loading.value=true;error.value=''
  const next=reset?1:page.value+1
  try{const res=await request.get('/social/contacts',{params:{kind:contactKind.value,q:search.value,page:next,size:30}});if(ticket!==generation)return;contacts.value=reset?res.data.records:[...contacts.value,...res.data.records];contactTotal.value=res.data.total;page.value=next}catch(e){if(ticket===generation)error.value=e instanceof Error?e.message:'联系人加载失败'}finally{if(ticket===generation)loading.value=false}
}
async function refresh(){
  error.value=''
  try{const settings=await request.get('/social/settings');featuresEnabled.value=settings.data.enabled!==false;allowRequests.value=settings.data.allowMessageRequests;if(!featuresEnabled.value){tab.value='messages';requests.value=[];return}const res=await request.get('/social/requests');requests.value=res.data||[];if(tab.value==='friends')await loadContacts(true)}catch(e){error.value=e instanceof Error?e.message:'消息请求加载失败'}
}
function chooseTab(key:string){tab.value=key;search.value='';if(key==='friends'){contactKind.value='friends';void loadContacts(true)}else if(key==='requests')void refresh()}
async function savePrivacy(allow:boolean){busy.value=true;try{await request.put('/social/settings',{allowMessageRequests:allow});allowRequests.value=allow;ElMessage.success('消息请求设置已保存')}catch(e){ElMessage.error(e instanceof Error?e.message:'保存失败')}finally{busy.value=false}}
async function unblock(id:string){try{await request.put(`/social/relationships/${id}/block`,{blocked:false});eventBus.emit('social:updated');await loadContacts(true)}catch(e){ElMessage.error(e instanceof Error?e.message:'解除拉黑失败')}}
watch(search,()=>{if(tab.value!=='friends')return;clearTimeout(timer);timer=setTimeout(()=>void loadContacts(true),250)})
watch(()=>props.refreshKey,refresh,{immediate:true})
onBeforeUnmount(()=>{generation++;clearTimeout(timer)})
</script>
<style scoped>
.social-sidebar{display:flex;flex-direction:column;height:100%;min-height:0;color:var(--ej-ink)}button,input{font:inherit}button{cursor:pointer}.social-heading{display:flex;align-items:center;justify-content:space-between;padding:20px 18px 12px}.social-heading h2{font-size:19px;margin:0}.social-heading button,.social-settings button,.contact-item>button,.social-empty button,.more{border:1px solid var(--ej-hairline);border-radius:999px;padding:6px 11px;background:var(--ej-surface);color:inherit}.social-tabs{display:flex;padding:0 12px;gap:5px}.social-tabs button{flex:1;border:0;border-radius:10px;padding:10px 2px;background:transparent;color:inherit}.social-tabs .active{background:var(--studio-lime,#c5ff45);font-weight:700}.social-tabs span{font-size:11px;margin-left:5px}.social-search{margin:14px 15px;padding:11px 13px;width:calc(100% - 30px);box-sizing:border-box;border:1px solid var(--ej-hairline);border-radius:12px;background:var(--ej-surface);color:inherit}.social-items{overflow-y:auto;flex:1;padding:0 7px}.social-conversation,.social-person{display:flex;align-items:center;gap:11px;border:0;background:transparent;color:inherit;text-align:left}.social-conversation{width:100%;padding:13px 10px;border-radius:12px}.social-conversation:hover,.social-conversation.selected{background:var(--ej-surface)}img{width:43px;height:43px;border-radius:50%;object-fit:cover;flex-shrink:0}.social-preview{flex:1;min-width:0}strong{display:block;font-size:14px}small{display:block;margin-top:5px;color:var(--ej-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px}i{font-style:normal;font-size:10px;color:var(--ej-muted);margin-left:5px}.social-unread{font-size:11px;background:#ffdfb8;min-width:18px;border-radius:99px;padding:2px 4px;text-align:center}.social-empty{padding:35px 14px;text-align:center;color:var(--ej-muted);line-height:1.8}.social-empty a,.social-empty button{display:block;margin:15px auto;color:inherit}.contact-item{display:flex;align-items:center;gap:5px;padding:12px 9px}.social-person{min-width:0;flex:1;padding:0}.social-person span{min-width:0}.social-settings{padding:10px 18px;font-size:12px;border-block:1px solid var(--ej-hairline)}.social-settings label{display:flex;align-items:center;gap:6px;margin-bottom:12px}.more{display:block;margin:12px auto}p[role=alert]{padding:10px;color:#984a35;font-size:12px}
</style>
