import test from 'node:test'
import assert from 'node:assert/strict'
import { linkCitations } from '../src/utils/citationLinks.ts'

test('source markers become numbered links to verified platform or web sources', () => {
  const rendered = linkCitations('平台[source:1] 网页[source:web2]', [
    { id: 'source:1', articleId: '42' }, { id: 'source:web2', url: 'https://example.org/tutorial?a=1&b=2' }
  ])
  assert.match(rendered, /href="\/article\/42"/)
  assert.match(rendered, /href="https:\/\/example.org\/tutorial\?a=1&amp;b=2"/)
  assert.match(rendered, />\[1\]<\/a>/)
  assert.match(rendered, />\[2\]<\/a>/)
  assert.match(rendered, /rel="noopener noreferrer"/)
  assert.equal(rendered.includes('source:'), false)
})

test('markers inside code and existing links retain their meaning', () => {
  const input = '`[source:1]`\n```text\n[source:1]\n```\n[source:1](https://example.org)'
  assert.equal(linkCitations(input, [{ id: 'source:1', articleId: '42' }]), input)
})

test('unknown sources and unsafe URLs cannot become clickable citations', () => {
  const input = '[source:1] [source:2] [source:3]'
  assert.equal(linkCitations(input, [
    { id: 'source:1', url: 'javascript:alert(1)' }, { id: 'source:2', articleId: '42" onclick="alert(1)' }
  ]), input)
})
