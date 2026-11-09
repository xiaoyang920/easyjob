import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

globalThis.window = new JSDOM('').window
const { editorSnapshotContent } = await import('../src/utils/editorTools.ts')

test('verbose formatting uses the complete text instead of a truncated HTML fragment', () => {
  const text = '这篇文章的完整正文。'
  const html = `<p style="${'color:red;'.repeat(4000)}">${text}</p>`
  const snapshot = editorSnapshotContent(html, text)
  assert.equal(snapshot.content, text)
  assert.equal(snapshot.content_format, 'text')
  assert.equal(snapshot.content_complete, true)
  assert.equal(snapshot.body_replaceable, false)
})

test('short rich text retains HTML and supports complete body replacement', () => {
  assert.deepEqual(editorSnapshotContent('<p>正文</p>', '正文'), {
    content: '<p>正文</p>', content_format: 'html', content_complete: true, body_replaceable: true
  })
})

test('long text and unread media remain explicitly incomplete', () => {
  const text = '正'.repeat(32001)
  const snapshot = editorSnapshotContent(`<p>${text}</p>`, text)
  assert.equal(snapshot.content.length, 32000)
  assert.equal(snapshot.content_complete, false)
  assert.equal(editorSnapshotContent('<p>正文</p><video src="movie.mp4"></video>', '正文').content_complete, false)
})
