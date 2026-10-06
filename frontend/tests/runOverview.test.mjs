import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeRunOverview, runLabel } from '../src/utils/runOverview.ts'
const item=(cid,status='running',rid='run-'+cid,time='2026-10-05T10:00:00Z')=>({runId:rid,conversationId:cid,title:'对话'+cid,status,updatedAt:time})
test('fresh visits avoid old-answer spam, tracked runs survive refresh and notify on completion',()=>{
  let state=mergeRunOverview({items:[],syncedAt:''},[item('1'),item('2','succeeded')],'2026-10-05T10:01:00Z')
  assert.equal(runLabel(state.items[0]),'正在生成')
  assert.equal(state.items[1].unread,false)
  state=mergeRunOverview(JSON.parse(JSON.stringify(state)),[item('1','succeeded'),item('2','succeeded')],'2026-10-05T10:02:00Z')
  assert.equal(runLabel(state.items[0]),'有新回复')
  state=mergeRunOverview(state,[item('1','succeeded'),item('2','succeeded')],'2026-10-05T10:03:00Z')
  assert.equal(state.items[0].unread,true)
  state.items[0].unread=false
  assert.equal(mergeRunOverview(state,[item('1','succeeded')],'2026-10-05T10:04:00Z').items[0].unread,false)
})
test('new results, approvals, errors, deleted chats and malformed rows remain distinct',()=>{
  const old={items:[{...item('1'),unread:false}],syncedAt:'2026-10-05T09:00:00Z'}
  const next=mergeRunOverview(old,[item('2','succeeded'),item('3','awaiting_approval'),item('4','failed'),{runId:9}], '2026-10-05T11:00:00Z')
  assert.equal(next.items.length,3)
  assert.equal(runLabel(next.items[0]),'有新回复')
  assert.equal(runLabel(next.items[1]),'等待确认')
  assert.equal(runLabel(next.items[2]),'生成中断')
  assert.ok(!next.items.some(r=>r.conversationId==='1'))
})
