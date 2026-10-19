import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { marked } from 'marked'
import { linkCitations, formatCitationHtml, draftBodyHtml } from '../src/utils/citationLinks.ts'
import { articleTextIndex } from '../src/utils/commentAnchors.ts'

const dom = new JSDOM('')
globalThis.DOMParser = dom.window.DOMParser
const sources = [{ id: 'research:web7', title: '学校简介', url: 'https://example.org/intro' }, { id: 'research:2', title: '平台文章', articleId: '42' }]
function body(html) { return new dom.window.DOMParser().parseFromString(html, 'text/html').body }

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

test('rendered Markdown has adjacent superscripts with source titles and no evidence-only paragraphs', () => {
  const html = formatCitationHtml(marked.parse('学校介绍。\n\n来源：[research:web7][research:2]'), sources)
  const root = body(html)
  assert.equal(root.querySelectorAll('p').length, 1)
  assert.equal(root.querySelectorAll('p > sup > a').length, 2)
  assert.equal(root.querySelector('a').href, 'https://example.org/intro')
  assert.equal(root.querySelector('a').title, '学校简介')
  assert.equal(root.querySelectorAll('a')[1].getAttribute('href'), '/article/42')
  assert.equal(root.textContent.includes('research:'), false)
  assert.equal(root.textContent.includes('来源：'), false)
})

test('broken CommonMark footnotes are removed only when the same paragraph has explicit evidence', () => {
  const html = formatCitationHtml(marked.parse('正文[^1]。\n\n来源：[research:web7]\n\n[^1]: 这是一段文字'), sources)
  const root = body(html)
  assert.equal(root.querySelectorAll('a').length, 1)
  assert.equal(root.querySelector('a').getAttribute('href'), 'https://example.org/intro')
  assert.equal(root.querySelectorAll('.citation-unavailable').length, 0)
  assert.equal(root.textContent.trim(), '正文。[1]')
  const missing = body(formatCitationHtml('<p>旧脚注<a href="%E9%BD%90%E9%B2%81">^1</a></p>'))
  assert.equal(missing.querySelectorAll('a').length, 0)
  assert.match(missing.querySelector('.citation-unavailable').title, /地址无效/)
})

test('code, explicit links, real footnote anchors and mathematical superscripts are preserved', () => {
  const html = '<pre><code>[research:web7]</code></pre><p><code>[research:2]</code> x<sup>2</sup> <a href="https://other.org">[research:web7]</a> <a href="#note1">^1</a></p><p id="note1">用户脚注</p>'
  const root = body(formatCitationHtml(html, sources))
  assert.equal(root.querySelector('pre').textContent, '[research:web7]')
  assert.equal(root.querySelector('p > code').textContent, '[research:2]')
  assert.equal(root.querySelector('sup').textContent, '2')
  assert.equal(root.querySelector('a').textContent, '[research:web7]')
  assert.equal(root.querySelector('a[href="#note1"]').textContent, '[1]')
  assert.equal(root.querySelector('a[href="#note1"]').target, '')
})

test('sanitized persisted superscripts are styled again, idempotently, without source metadata', () => {
  const html = '<p>学校介绍<sup><a href="https://example.org/intro" title="学校简介">[3]</a></sup></p>'
  const result = formatCitationHtml(html)
  assert.equal(formatCitationHtml(result), result)
  const root = body(result)
  assert.equal(root.querySelector('sup').className, 'citation-ref')
  assert.equal(root.querySelector('a').className, 'inline-citation')
  assert.match(root.querySelector('a').getAttribute('aria-label'), /学校简介/)
})

test('legacy article styling preserves canonical quote text and offsets exactly', () => {
  const html = '<h2>介绍</h2><p>学校成立于某年<a href="%E6%91%98%E8%A6%81">^1</a>。</p><p>来源：[research:web7][research:2]</p><p>后面的文字可划线评论。</p>'
  const before = articleTextIndex(body(html)).text
  const root = body(formatCitationHtml(html, [], true))
  assert.equal(articleTextIndex(root).text, before)
  assert.equal(root.querySelectorAll('p').length, 3)
  assert.equal(root.querySelectorAll('.citation-raw-label').length, 3)
  assert.equal(root.querySelector('.citation-source-label').textContent, '来源：')
  assert.equal(root.querySelectorAll('a').length, 0)
})

test('unresolved sources and unsafe source URLs are visible without fabricated clickable destinations', () => {
  const html = formatCitationHtml('<p>[missing:web1] [research:web7]</p>', [{ ...sources[0], url: 'javascript:alert(1)' }])
  const root = body(html)
  assert.equal(root.querySelectorAll('a').length, 0)
  assert.equal(root.querySelectorAll('.citation-unavailable').length, 2)
  assert.equal(root.textContent.includes('missing:'), false)
})

test('draft prose hides evidence markers and source-only paragraphs while chat keeps links', () => {
  const input = marked.parse('[research:web7]学校介绍[research:2]。\n\n来源：[research:web7][research:2]')
  const draft = body(draftBodyHtml(input, sources))
  assert.equal(draft.textContent.trim(), '学校介绍。')
  assert.equal(draft.querySelectorAll('p').length, 1)
  assert.equal(draft.querySelectorAll('sup,a').length, 0)
  assert.equal(body(formatCitationHtml(input, sources)).querySelectorAll('a.inline-citation').length, 2)
  assert.equal(draftBodyHtml(draft.innerHTML, sources), draft.innerHTML)
})

test('draft cleanup retains code, authored links, mathematical superscripts and real footnotes', () => {
  const input = marked.parse('正文[research:web7]，数组[1]。\n\n`[research:2]`\n\n~~~text\n[research:web7]\n~~~\n\n[research:web7](https://other.example.org)\n\n[^1]: https://example.org/note\n\n普通脚注[^1]。') + '<p>x<sup>2</sup> <a href="#note1">^1</a></p><p id="note1">真实脚注</p>'
  const draft = body(draftBodyHtml(input, sources))
  assert.ok(draft.textContent.includes('正文，数组[1]。'))
  assert.equal(draft.querySelector('pre').textContent.trim(), '[research:web7]')
  assert.equal(draft.querySelector('p > code').textContent, '[research:2]')
  assert.equal(draft.querySelector('a[href="https://other.example.org"]').textContent, 'research:web7')
  assert.equal(draft.querySelector('a[href="https://example.org/note"]').textContent, '^1')
  assert.equal(draft.querySelector('sup').textContent, '2')
  assert.equal(draft.querySelector('a[href="#note1"]').textContent, '^1')
  assert.equal(body(draftBodyHtml('<p>来源：<code>[research:web7]</code></p>', sources)).textContent, '来源：[research:web7]')
})

test('draft cleanup handles old grounding paragraphs and generated badges without exposing internal IDs', () => {
  const input = marked.parse('介绍[^1]。\n\n来源：[research:web7]\n\n[^1]: 一段摘要\n\n## 标题\n\n来源：[missing:web1]')
  assert.equal(body(draftBodyHtml(input, sources)).textContent.trim().replace(/\n+/g, '\n'), '介绍。\n标题')
  const savedPreview = '<p>正文<sup class="citation-ref"><a class="inline-citation" href="https://example.org/intro">[1]</a></sup>。</p>'
  assert.equal(body(draftBodyHtml(savedPreview, sources)).textContent, '正文。')
  assert.equal(body(draftBodyHtml('<p>正文[1][research:web7]。</p>', [{ id: '1' }])).textContent, '正文。')
})
