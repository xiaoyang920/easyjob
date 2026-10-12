import test from 'node:test'
import assert from 'node:assert/strict'
import { editableArticleStatus, savedArticlePath } from '../src/utils/articleLifecycle.ts'

test('historical AI draft links open the current published article', () => {
  assert.equal(savedArticlePath('23775876431093760', 1), '/article/23775876431093760')
  assert.equal(savedArticlePath('23775876431093760', 0), '/edit-article?id=23775876431093760')
})

test('unknown, missing and moderated states cannot default to draft', () => {
  for (const status of [undefined, null, 2, 3, -1, '0', '1']) {
    assert.throws(() => editableArticleStatus(status))
    assert.throws(() => savedArticlePath('42', status))
  }
})

test('published articles with a new working revision open that draft, while approved versions stay public', () => {
  for (const revisionState of [0, 1, 3, 4]) {
    assert.equal(savedArticlePath('42',1,{revisionState,revisionId:'5'}),'/edit-article?id=42')
  }
  assert.equal(savedArticlePath('42',1,{revisionState:2,revisionId:'5'}),'/article/42')
  assert.equal(savedArticlePath('42',1,{revisionState:0,revisionId:'0'}),'/article/42')
})
