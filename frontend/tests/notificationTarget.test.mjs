import test from 'node:test'
import assert from 'node:assert/strict'
import {notificationPath,isReviewNotification} from '../src/utils/notificationTarget.ts'
test('approval opens the published article without a comment anchor',()=>{
  assert.equal(notificationPath({type:6,articleId:'42',targetId:'123'}),'/article/42')
})
test('rejection opens the exact reviewed snapshot even after later edits',()=>{
  assert.equal(notificationPath({type:7,articleId:'42',targetId:'9223372036854770000'}),'/draft-box?articleId=42&revisionId=9223372036854770000')
  assert.equal(notificationPath({type:7,articleId:'42'}),'/draft-box?articleId=42')
})
test('existing comment and follow destinations keep working',()=>{
  assert.equal(notificationPath({type:1,articleId:'42',targetId:'123'}),'/article/42#comment-123')
  assert.equal(notificationPath({type:4,targetId:'7'}),'/user-space/7')
  assert.equal(notificationPath({type:5}),undefined)
  assert.equal(isReviewNotification(6),true);assert.equal(isReviewNotification(7),true);assert.equal(isReviewNotification(5),false)
})
