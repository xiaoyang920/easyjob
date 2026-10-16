import test from 'node:test'
import assert from 'node:assert/strict'
import {draftSignature,recoveryKey,readRecovery,saveRecovery} from '../src/utils/draftRecovery.ts'
import {compareLines} from '../src/utils/revisionDiff.ts'

test('draft recovery is isolated by owner and article, survives reload and handles quotas',()=>{
 const values=new Map(),store={getItem:key=>values.get(key)??null,setItem:(key,v)=>values.set(key,v)}
 const key=recoveryKey('7','42'),snapshot={updatedAt:Date.now(),signature:'s',article:{title:'未保存'},content:'正文',tags:[]}
 assert.equal(saveRecovery(store,key,snapshot),true);assert.deepEqual(readRecovery(store,key),snapshot)
 assert.equal(readRecovery(store,recoveryKey('8','42')),null);assert.equal(readRecovery(store,recoveryKey('7','43')),null)
 assert.equal(saveRecovery({setItem(){throw Error('quota')}},key,snapshot),false)
 values.set(key,'{');assert.equal(readRecovery(store,key),null)
 values.set(key,JSON.stringify({...snapshot,updatedAt:Date.now()-8*86400000}));assert.equal(readRecovery(store,key),null)
})
test('editor signature tracks content but excludes revision locks',()=>{
 const a={title:'A',categoryId:'2',lockVersion:1,revisionId:'10'}
 assert.equal(draftSignature(a,'正文',[]),draftSignature({...a,lockVersion:2,revisionId:'11'},'正文',[]))
 assert.notEqual(draftSignature(a,'正文',[]),draftSignature(a,'新增正文',[]))
})
test('revision comparison reconstructs both versions without losing lines',()=>{
 for(const [a,b] of [['a\nb\nc','a\nnew\nc'],['','new'],['same','same'],['line\n','line'],[Array.from({length:1000},(_,i)=>'old'+i).join('\n'),Array.from({length:1000},(_,i)=>'new'+i).join('\n')]]){
  const diff=compareLines(a,b)
  assert.equal(diff.filter(l=>l.kind!=='add').map(l=>l.text).join('\n'),a)
  assert.equal(diff.filter(l=>l.kind!=='remove').map(l=>l.text).join('\n'),b)
 }
})
