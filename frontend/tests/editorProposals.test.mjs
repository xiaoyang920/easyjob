import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

globalThis.window = new JSDOM('').window
const { createEditorProposalController } = await import('../src/utils/editorProposals.ts')

function fixture(source = { html: '<p>正文</p>', text: '正文', selection: '', range: null }) {
  const fields = { title: '原标题', summary: '' }
  const released = []
  let editable = true, summaryOpened = false, bodyWrites = 0
  const editor = { readDocument: () => source, captureSnapshot() {}, releaseSnapshot: id => released.push(id),
    clearSnapshots() {}, applyProposal() { bodyWrites++; return { ok: true, message: '正文已更新' } },
    undoProposal() { return { ok: true, message: '已撤销' } } }
  const controller = createEditorProposalController({ getEditor: () => editor, getFields: () => fields,
    canEdit: () => editable, onSummaryApplied: () => { summaryOpened = true } })
  const proposal = (snapshot, target = 'summary') => ({ id: crypto.randomUUID(), documentId: snapshot.document_id,
    snapshotId: snapshot.snapshot_id, target, before: target === 'body' ? snapshot.content : snapshot[target],
    after: '新摘要', explanation: '', format: target === 'body' ? 'markdown' : 'text' })
  return { fields, released, controller, proposal, disable: () => { editable = false },
    summaryOpened: () => summaryOpened, bodyWrites: () => bodyWrites }
}

test('summary apply and undo preserve unrelated metadata and never write the body', () => {
  const context = fixture()
  const proposal = context.proposal(context.controller.read())
  context.fields.title = '用户新标题'
  assert.equal(context.controller.apply(proposal).ok, true)
  assert.equal(context.fields.summary, '新摘要')
  assert.equal(context.summaryOpened(), true)
  assert.equal(context.bodyWrites(), 0)
  assert.equal(context.controller.undo(proposal).ok, true)
  assert.deepEqual(context.fields, { title: '用户新标题', summary: '' })
})

test('changed summaries and read-only documents never accept stale proposals', () => {
  const context = fixture()
  const proposal = context.proposal(context.controller.read())
  context.fields.summary = '用户自己输入'
  assert.equal(context.controller.apply(proposal).ok, false)
  assert.equal(context.fields.summary, '用户自己输入')
  context.disable()
  assert.equal(context.controller.read(), null)
  assert.equal(context.controller.apply(proposal).ok, false)
})

test('expired snapshots and document changes invalidate old proposals', () => {
  const context = fixture()
  const first = context.proposal(context.controller.read())
  for (let count = 0; count < 8; count++) context.controller.read()
  assert.equal(context.released[0], first.snapshotId)
  assert.equal(context.controller.apply(first).ok, false)
  const latest = context.proposal(context.controller.read())
  context.controller.reset()
  assert.equal(context.controller.apply(latest).ok, false)
})

test('complete text from oversized rich formatting can be summarized but not replace the body', () => {
  const context = fixture({ html: `<p style="${'color:red;'.repeat(4000)}">完整正文</p>`, text: '完整正文', selection: '', range: null })
  const snapshot = context.controller.read()
  assert.equal(snapshot.content, '完整正文')
  assert.equal(snapshot.content_complete, true)
  assert.equal(context.controller.apply(context.proposal(snapshot, 'body')).ok, false)
  assert.equal(context.bodyWrites(), 0)
  assert.equal(context.controller.apply(context.proposal(snapshot)).ok, true)
})
