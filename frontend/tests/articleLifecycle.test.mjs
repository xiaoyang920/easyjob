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
