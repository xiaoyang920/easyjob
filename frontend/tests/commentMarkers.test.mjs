import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { articleTextIndex } from '../src/utils/commentAnchors.ts'
import { groupCommentMarkers, markerIdsAt } from '../src/utils/commentMarkers.ts'

test('comments sharing the current span group together despite separate stored anchors', () => {
  const root = new JSDOM('<main><p>前文 这是原文 后文</p></main>').window.document.querySelector('main')
  const text = articleTextIndex(root).text, start = text.indexOf('这是原文')
  const quote = { exact:'这是原文', start, end:start+4, prefix:text.slice(0,start), suffix:text.slice(start+4) }
  const groups = groupCommentMarkers(root,[{commentId:'101',quote},{commentId:'102',quote},{commentId:'101',quote}])
  assert.equal(groups.length,1); assert.deepEqual(groups[0].ids,['101','102'])
  assert.equal(groups[0].range.toString(),'这是原文')
  root.prepend(root.ownerDocument.createTextNode('插入说明 '))
  assert.deepEqual(groupCommentMarkers(root,[{commentId:'101',quote},{commentId:'102',quote}])[0].ids,['101','102'])
})

test('removed text gets no persistent line or accidental group', () => {
  const root = new JSDOM('<main>新的正文</main>').window.document.querySelector('main')
  assert.deepEqual(groupCommentMarkers(root,[{commentId:'1',quote:{exact:'旧正文',prefix:'',suffix:'',start:0,end:3}}]),[])
})

test('hit testing merges overlapping groups, ignores empty space and allows tapping underline', () => {
  const a = { ids:['1','2'] }, b = { ids:['2','3'] }
  const boxes = [{group:a,left:10,top:20,width:100,height:18},{group:b,left:50,top:20,width:70,height:18}]
  assert.deepEqual(markerIdsAt(boxes,70,38),['1','2','3'])
  assert.deepEqual(markerIdsAt(boxes,20,40),['1','2'])
  assert.deepEqual(markerIdsAt(boxes,500,20),[])
})
