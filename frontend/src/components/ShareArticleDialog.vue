<template>
  <el-dialog :model-value="modelValue" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" title="分享文章" width="min(520px,92vw)" append-to-body @update:model-value="$emit('update:modelValue',$event)">
    <div class="share-friend-form">
      <template v-if="allowFriendShare">
        <div v-if="card?.available" class="share-card"><img v-if="card.coverImage" :src="avatarUrl(card.coverImage)" alt=""><div><strong>{{card.title}}</strong><small>{{card.authorName}} · 文章</small></div></div>
        <p v-if="articleLoading" class="share-hint" role="status">正在加载文章…</p>
        <p v-else-if="card && !card.available" class="share-hint" role="status">这篇文章目前不可分享给朋友</p>
        <p v-if="articleError" role="alert">{{articleError}} <button :disabled="articleLoading" @click="loadArticle">重试</button></p>
        <label for="share-friend-search" class="share-section-title">分享给朋友</label>
        <input id="share-friend-search" v-model="search" :disabled="busy" placeholder="搜索昵称或备注" @input="searchFriends">
        <p v-if="friendsError" role="alert">{{friendsError}} <button :disabled="loading" @click="loadFriends()">重试</button></p>
        <div v-if="friends.length" class="share-friends" role="radiogroup" aria-label="选择分享对象">
          <label v-for="friend in friends" :key="friend.userId" class="share-friend" :class="{selected:target===String(friend.userId)}" :title="friend.remark||friend.nickName">
            <input v-model="target" type="radio" name="article-share-friend" :value="String(friend.userId)" :disabled="busy">
            <span class="share-avatar"><img :src="avatarUrl(friend.avatar,friend.nickName)" alt="" @error="onAvatarError($event,friend.nickName)"><i v-if="target===String(friend.userId)" aria-hidden="true">✓</i></span>
            <strong>{{friend.remark||friend.nickName}}</strong><small v-if="friend.remark">{{friend.nickName}}</small>
          </label>
        </div>
        <p v-if="loading" class="share-hint" role="status">正在加载朋友…</p>
        <p v-else-if="!friends.length && !friendsError" class="share-hint">{{search?'没有找到相关朋友':'暂无朋友，互相关注后就能在这里分享。'}}</p>
        <button v-if="friends.length<total" class="share-more" :disabled="loading || busy" @click="loadFriends(false)">加载更多朋友</button>
        <p v-if="error" role="alert">{{error}}</p>
        <button class="share-submit" :disabled="busy || !target || !card?.available" @click="send">{{busy?'发送中…':`发送给${selectedName||'朋友'}`}}</button>
      </template>
      <p v-else class="share-hint">这篇文章暂不支持分享给朋友，可以复制链接。</p>
      <div class="share-other"><button type="button" :disabled="busy" @click="$emit('copy-link')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 13 4-4m-6 6-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/></svg>复制链接</button></div>
    </div>
  </el-dialog>
</template>
<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue'
import {ElMessage} from 'element-plus'
import request from '@/utils/request'
import {eventBus} from '@/utils/eventBus'
import {avatarUrl,onAvatarError} from '@/utils/avatar'
const props=withDefaults(defineProps<{modelValue:boolean;articleId:string;allowFriendShare?:boolean}>(),{allowFriendShare:true})
const emit=defineEmits<{'update:modelValue':[value:boolean];sent:[articleId:string];'copy-link':[]}>()
const card=ref<any>(),friends=ref<any[]>([]),target=ref(''),search=ref(''),error=ref(''),articleError=ref(''),friendsError=ref(''),busy=ref(false),loading=ref(false),articleLoading=ref(false),total=ref(0)
let articleTicket=0
let attempt:{key:string;id:string}|undefined,timer:ReturnType<typeof setTimeout>|undefined,generation=0,page=0
const selectedName=computed(()=>{const person=friends.value.find(f=>String(f.userId)===target.value);return person?.remark||person?.nickName})
async function loadArticle(){const run=++articleTicket;articleError.value='';articleLoading.value=true;try{const res=await request.get(`/social/articles/${props.articleId}`);if(run===articleTicket&&props.modelValue)card.value=res.data}catch(e){if(run===articleTicket)articleError.value=e instanceof Error?e.message:'文章加载失败'}finally{if(run===articleTicket)articleLoading.value=false}}
async function loadFriends(reset=true){const ticket=++generation;loading.value=true;friendsError.value='';const next=reset?1:page+1;try{const res=await request.get('/social/contacts',{params:{kind:'friends',q:search.value,page:next,size:30}});if(ticket!==generation)return;friends.value=reset?res.data.records:[...friends.value,...res.data.records];total.value=res.data.total;page=next}catch(e){if(ticket===generation)friendsError.value=e instanceof Error?e.message:'朋友加载失败'}finally{if(ticket===generation)loading.value=false}}
function searchFriends(){target.value='';friends.value=[];total.value=0;generation++;clearTimeout(timer);timer=setTimeout(()=>void loadFriends(true),250)}
async function send(){if(!target.value||!card.value?.available||busy.value)return;busy.value=true;error.value='';const selectedTarget=target.value,selectedArticle=card.value.articleId;const key=`${selectedTarget}:${selectedArticle}`;if(attempt?.key!==key)attempt={key,id:crypto.randomUUID()};try{const opened=await request.post('/chat/conversation/create',{targetUserId:selectedTarget});const sent=await request.post('/chat/message/send',{conversationId:opened.data.conversationId,messageType:3,articleId:selectedArticle,clientMessageId:attempt.id});if(sent.code!==200)throw new Error(sent.message||'发送失败');attempt=undefined;ElMessage.success('文章已分享');eventBus.emit('social:updated');emit('sent',String(selectedArticle));emit('update:modelValue',false)}catch(e){error.value=e instanceof Error?e.message:'发送失败，可重试'}finally{busy.value=false}}
watch(()=>[props.modelValue,props.articleId,props.allowFriendShare],()=>{generation++;articleTicket++;clearTimeout(timer);if(props.modelValue){card.value=undefined;friends.value=[];total.value=0;error.value='';articleError.value='';friendsError.value='';target.value='';search.value='';if(props.allowFriendShare){void loadFriends();void loadArticle()}}})
onBeforeUnmount(()=>{generation++;articleTicket++;clearTimeout(timer)})
</script>
<style scoped>
.share-friend-form{display:grid;gap:14px;color:var(--ej-ink)}input,button{font:inherit}.share-friend-form>input{padding:11px 14px;border:1px solid var(--ej-hairline);border-radius:99px;background:var(--ej-surface);color:inherit;min-width:0}.share-card{display:flex;gap:12px;padding:14px;background:var(--ej-canvas);border-radius:12px}.share-card>div{min-width:0}.share-card img{width:70px;height:55px;object-fit:cover;border-radius:6px}.share-card strong,.share-card small{display:block}.share-card small{margin-top:6px;color:var(--ej-muted)}.share-section-title{font-weight:700}.share-friends{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;max-height:280px;overflow-y:auto;padding:3px}.share-friend{position:relative;display:flex;flex-direction:column;align-items:center;gap:6px;padding:12px 5px;border:1px solid transparent;border-radius:12px;cursor:pointer;min-width:0}.share-friend:hover{background:var(--ej-canvas)}.share-friend.selected{border-color:var(--ej-ink);background:#c5ff4526}.share-friend:focus-within{outline:2px solid var(--ej-ink);outline-offset:1px}.share-friend input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer;z-index:1}.share-avatar{position:relative;width:52px;height:52px}.share-avatar img{width:100%;height:100%;border-radius:50%;object-fit:cover}.share-avatar i{position:absolute;bottom:-2px;right:-4px;display:grid;place-items:center;width:21px;height:21px;border:1px solid var(--ej-ink);border-radius:50%;background:var(--studio-lime,#c5ff45);font-style:normal}.share-friend strong,.share-friend small{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.share-friend small{color:var(--ej-muted);font-size:11px}.share-submit{padding:12px;border:1px solid var(--ej-ink);border-radius:99px;background:var(--studio-lime,#c5ff45);cursor:pointer}.share-submit:disabled{opacity:.5;cursor:default}.share-hint{margin:0;padding:14px 0;text-align:center;font-size:13px;color:var(--ej-muted)}.share-other{display:flex;justify-content:center;padding-top:14px;border-top:1px solid var(--ej-hairline)}.share-other button,.share-more{display:flex;align-items:center;justify-content:center;gap:8px;border:0;background:transparent;color:inherit;cursor:pointer;padding:8px 15px}.share-other svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.share-more{margin:auto;font-size:12px}p[role=alert]{margin:0;color:#984a35;font-size:13px}p[role=alert] button{border:0;background:transparent;color:inherit;text-decoration:underline;cursor:pointer}@media(max-width:420px){.share-friends{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>
