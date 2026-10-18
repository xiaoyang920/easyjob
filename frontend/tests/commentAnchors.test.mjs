import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { articleTextIndex, selectedQuote, resolveQuote, quoteRange } from '../src/utils/commentAnchors.ts'

function fixture(html) {
  const dom = new JSDOM(`<main id="root">${html}</main><aside>outside</aside>`)
  return { window: dom.window, root: dom.window.document.getElementById('root') }
}
function select(window, start, from, end = start, to = start.textContent.length) {
  const range = window.document.createRange(); range.setStart(start, from); range.setEnd(end, to)
  const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
  return selection
}

test('canonical text respects blocks, CJK, emoji, inline code and ignores generated toolbars', () => {
  const { root } = fixture('<h2>标题</h2><p>一段 <strong>正文🙂</strong><br>下一行</p><pre><div class="article-code-toolbar">java 放大查看</div><code>if (x) {\n  return 1;\n}</code></pre>')
  assert.equal(articleTextIndex(root).text, '标题 一段 正文🙂 下一行 if (x) { return 1; }')
})

test('cross-inline and cross-paragraph selections produce stable offsets and restorable ranges', () => {
  const { window, root } = fixture('<p>前文 <strong>选择这句</strong> 继续</p><p>下一段文字</p>')
  const start = root.querySelector('strong').firstChild, end = root.lastChild.firstChild
  const quote = selectedQuote(root, select(window, start, 0, end, 3))
  assert.equal(quote.exact, '选择这句 继续 下一段')
  assert.equal(articleTextIndex(root).text.slice(quote.start, quote.end), quote.exact)
  assert.equal(articleTextIndex(quoteRange(root, quote).cloneContents()).text, quote.exact)
})

test('repeated text attaches to selected occurrence and survives preceding insertion', () => {
  const { window, root } = fixture('<p>第一段：相同句子</p><p>第二段：相同句子</p>')
  const node = root.lastChild.firstChild
  const quote = selectedQuote(root, select(window, node, 4))
  assert.equal(quote.exact, '相同句子')
  const previous = quote.start
  root.prepend(window.document.createTextNode('新增说明 '))
  assert.ok(resolveQuote(articleTextIndex(root).text, quote) > previous)
  assert.equal(quoteRange(root, quote).startContainer, node)
})

test('removed and ambiguous quotes are not attached arbitrarily', () => {
  const quote = { exact: '重复', prefix: '旧前文', suffix: '旧后文', start: 500, end: 502 }
  assert.equal(resolveQuote('重复 另外一段 重复', quote), undefined)
  assert.equal(resolveQuote('文字已经修改', quote), undefined)
  assert.equal(resolveQuote('新增 唯一的重复 结尾', quote), undefined)
})

test('unrelated, empty, and overlong selection never create an anchor', () => {
  const { window, root } = fixture('<p>正文</p>')
  assert.equal(selectedQuote(root, window.getSelection()), undefined)
  const outside = window.document.querySelector('aside').firstChild
  assert.equal(selectedQuote(root, select(window, outside, 0)), undefined)
  root.textContent = '字'.repeat(1001)
  assert.equal(selectedQuote(root, select(window, root.firstChild, 0)), undefined)
})

test('UTF-16 offsets and context windows preserve emoji pairs', () => {
  const { window, root } = fixture(`<p>${'🙂'.repeat(26)}目标${'🙂'.repeat(26)}</p>`)
  const quote = selectedQuote(root, select(window, root.firstChild.firstChild, 52, root.firstChild.firstChild, 54))
  assert.equal(quote.exact, '目标')
  assert.equal(quote.start, 52)
  assert.ok(!/[\uDC00-\uDFFF]/.test(quote.prefix[0]))
  assert.ok(!/[\uD800-\uDBFF]/.test(quote.suffix.at(-1)))
  assert.equal(quoteRange(root, quote).toString(), '目标')
})
