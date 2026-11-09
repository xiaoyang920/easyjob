import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeRunOverview, readReceiptMatches, runCategory, runLabel } from '../src/utils/runOverview.ts'
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

test('a new terminal version of the same recovered run is a new update', () => {
  const old = { items: [{ ...item('1', 'failed'), unread: false }], syncedAt: '2026-10-05T10:00:00Z' }
  const next = mergeRunOverview(old, [item('1', 'failed', 'run-1', '2026-10-05T11:00:00Z')], '2026-10-05T11:01:00Z')
  assert.equal(next.items[0].unread, true)
  assert.equal(readReceiptMatches({ runId: 'run-1', status: 'failed', updatedAt: old.items[0].updatedAt, seenAt: 1 }, next.items[0]), false)
})

test('live read receipts acknowledge terminal replies before polling catches up, never running or other runs', () => {
  const pending = { runId: 'run-1', seenAt: 1 }
  assert.equal(readReceiptMatches(pending, item('1', 'succeeded')), true)
  assert.equal(readReceiptMatches(pending, item('1')), false)
  assert.equal(readReceiptMatches(pending, item('1', 'succeeded', 'other')), false)
  assert.equal(readReceiptMatches(pending, { ...item('1', 'succeeded'), generation: 1 }), false,
    'an unconfirmed read receipt cannot hide a later recovery while the browser was closed')
})

test('navigation labels retain the published article, draft, and general conversation types', () => {
  assert.equal(runCategory({ ...item('1'), scope: 'article' }), '文章问答')
  assert.equal(runCategory({ ...item('1'), scope: 'writing' }), '草稿写作')
  assert.equal(runCategory(item('1')), '普通聊天')
})
