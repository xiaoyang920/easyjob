import { test } from 'node:test'
import assert from 'node:assert/strict'
import { articleTextStyle, blockIndentPixels, indentPixels } from '../src/utils/articleTextStyle.ts'

test('relative legacy indents migrate using the document baseline, independent of font size', () => {
  assert.equal(indentPixels('2em'), 32)
  assert.equal(indentPixels('32px'), 32)
  assert.equal(indentPixels('99999em'), null)
  assert.equal(indentPixels('-32px'), null)
  assert.equal(articleTextStyle('p', 'font-size:48px;text-indent:2em'), 'font-size: 48px; text-indent: 32px;')
})

test('block depth round trips independently of first-line formatting with bounded layout styles', () => {
  assert.equal(articleTextStyle('p','line-height:1.625'), 'line-height: 1.625;')
  assert.equal(articleTextStyle('h3', 'margin-left:64px;text-indent:32px'), 'margin-left: 64px; text-indent: 32px;')
  assert.equal(blockIndentPixels('256px'), 256)
  for (const value of ['-32px','16px','1em','32.5px','288px','calc(32px)','32px!important']) {
    assert.equal(blockIndentPixels(value), null)
    assert.equal(articleTextStyle('p', `margin-left:${value}`), '')
  }
  for (const tag of ['span','img','table','pre']) assert.equal(articleTextStyle(tag, 'margin-left:32px'), '')
})
test('author formatting is retained without permitting layout or resource CSS', () => {
  const style = articleTextStyle('p', 'font-size:32px;line-height:2;text-align:right;color:rgba(10,20,30,0.5);text-indent:64px;position:fixed;inset:0;background-image:url(https://evil.example/x);--custom:red')
  assert.equal(style, 'font-size: 32px; line-height: 2; text-align: right; color: rgba(10,20,30,0.5); text-indent: 64px;')
  for (const value of ['url(https://evil.example/x)', 'var(--color)', 'expression(alert(1))', 'rgb(999,0,0)', 'rgba(1,2,3,2)', 'red!important']) {
    assert.equal(articleTextStyle('span', `color:${value}`), '')
  }
  assert.equal(articleTextStyle('img', 'font-size:32px;text-indent:32px'), '')
  assert.equal(articleTextStyle('p', 'font-size:999px;line-height:20;text-indent:99999px'), '')
})
