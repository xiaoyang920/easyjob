import { reactive } from 'vue'
import request from './request'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from './eventBus'

export type Relationship = {userId:string;isFollowing:boolean;isFollowedBy:boolean;isFriend:boolean;isBlockedByMe:boolean;remark?:string}
export const relationships = reactive<Record<string,Relationship>>({})
const queued = new Set<string>()
let scheduled = false
export function relationshipLabel(value?:Relationship) {
  return value?.isBlockedByMe ? '已拉黑' : value?.isFollowing ? value.isFollowedBy ? '互相关注' : '已关注' : value?.isFollowedBy ? '回关' : '关注'
}
export async function refreshRelationships(ids:string[]) {
  if (!localStorage.getItem('token') || !ids.length) return
  const owner = localStorage.getItem('userId')
  const unique=[...new Set(ids)]
  for(let offset=0;offset<unique.length;offset+=100){
    const res=await request.get('/social/relationships',{params:{ids:unique.slice(offset,offset+100).join(',')}})
    if(owner!==localStorage.getItem('userId'))return
    for(const row of res.data||[])relationships[String(row.userId)]=row
  }
}
export function queueRelationship(id:string) {
  if (!id || !localStorage.getItem('token') || id===localStorage.getItem('userId')) return
  queued.add(id)
  if (scheduled) return
  scheduled = true
  queueMicrotask(() => { scheduled=false; const ids=[...queued];queued.clear();void refreshRelationships(ids).catch(()=>{}) })
}
export async function changeFollow(id:string,value:boolean) {
  const owner=localStorage.getItem('userId')
  const res:any = await request.put(`/social/relationships/${id}/follow`,{following:value})
  if(owner!==localStorage.getItem('userId'))throw new Error('账号已切换，请刷新后重试')
  if (res.code !== 200) throw new Error(res.message || '关注操作失败')
  relationships[id]=res.data;eventBus.emit('social:updated');return res.data as Relationship
}
function clear(){for(const id of Object.keys(relationships))delete relationships[id]}
eventBus.on(EVENT_AUTH_CHANGED,clear);eventBus.on(EVENT_AUTH_EXPIRED,clear)
eventBus.on('social:updated',()=>void refreshRelationships(Object.keys(relationships)).catch(()=>{}))
