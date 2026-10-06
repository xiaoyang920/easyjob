import test from 'node:test'
import assert from 'node:assert/strict'
import { searchSegments } from '../src/utils/searchHighlight.ts'

test('regex metacharacters remain literal search terms', () => {
  for (const keyword of ['C++', '[', '.*', '(a)', '$', '\\']) {
    const segments = searchSegments(`before ${keyword} after`, keyword)
    assert.deepEqual(segments.filter(p => p.highlighted).map(p => p.text), [keyword])
    assert.equal(segments.map(p => p.text).join(''), `before ${keyword} after`)
  }
})
test('only the ES marker is interpreted, malicious markup remains inert text', () => {
  const value = `<img src=x onerror=alert(1)><span class='highlight'>Redis</span><script>alert(2)</script>`
  const segments = searchSegments(value, '', true)
  assert.deepEqual(segments, [{ text: '<img src=x onerror=alert(1)>', highlighted: false }, { text: 'Redis', highlighted: true }, { text: '<script>alert(2)</script>', highlighted: false }])
})
test('arbitrary tags, entities and plain nicknames are retained as text', () => {
  const value = '<span class="highlight" onclick="x()">&lt;Admin&gt;</span>'
  assert.equal(searchSegments(value, '', true).map(p => p.text).join(''), '<span class="highlight" onclick="x()">&lt;Admin&gt;')
  assert.equal(searchSegments('<b>Admin</b>', '').map(p => p.text).join(''), '<b>Admin</b>')
})
test('case-insensitive repeated matches preserve original casing', () => {
  assert.deepEqual(searchSegments('Redis redis REDIS', 'redis').filter(p => p.highlighted).map(p => p.text), ['Redis', 'redis', 'REDIS'])
})
