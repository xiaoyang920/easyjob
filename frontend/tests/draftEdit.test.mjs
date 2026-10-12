import test from 'node:test'
import assert from 'node:assert/strict'
import {draftEditFrom,draftEditError} from '../src/utils/draftEdit.ts'

test('loads complete interrupted Markdown without stripping links, images or code',()=>{
 const body='# 标题\n![图片](/uploads/a.png)\n```java\nint n=1;\n```'
 assert.deepEqual(draftEditFrom({title:'标题',summary:'摘要',draft:body},'fallback'),{title:'标题',summary:'摘要',content:body})
})
test('validates Unicode character counts consistently with backend',()=>{
 const draft={title:'🙂'.repeat(50),summary:'🙂'.repeat(500),content:'正文'}
 assert.equal(draftEditError(draft),'')
 assert.match(draftEditError({...draft,title:draft.title+'🙂'}),/标题/)
 assert.match(draftEditError({...draft,summary:draft.summary+'🙂'}),/摘要/)
 for(const content of ['', '  \n', '字'.repeat(100001)])assert.match(draftEditError({...draft,content}),/正文/)
})

test('recovered rich-text approvals keep their explicit content format',()=>{
 const draft=draftEditFrom({title:'标题',summary:'',draft:'<h2>标题</h2><p>内容</p>',contentFormat:'html'})
 assert.equal(draft.content_format,'html')
 assert.equal(draftEditError(draft),'')
 assert.equal(draftEditFrom({title:'标题',draft:'# 标题'}).content_format,undefined)
})
