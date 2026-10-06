import { test } from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
globalThis.window = new JSDOM('').window
const { safeHtml } = await import('../src/utils/safeHtml.ts')

test('model HTML cannot execute scripts, handlers, SVG or unsafe URLs', () => {
  const html = safeHtml('<script>x()</script><svg onload="x()"></svg><img src="/uploads/a.jpg" onerror="x()"><a href="javascript:x()">x</a><iframe srcdoc="x"></iframe><p style="color:red">text</p>')
  assert.doesNotMatch(html, /script|onerror|onload|javascript:|iframe|<svg|style=/)
  assert.match(html, /src="\/uploads\/a.jpg"/)
})
test('normal Markdown, code, tables and citation links survive', () => {
  const html = safeHtml('<pre class="streaming-table"><code class="language-java">a &lt; b</code></pre><table><tr><td>cell</td></tr></table><a href="/article/42" class="citation-link">[1]</a>')
  assert.match(html, /language-java/); assert.match(html, /<table>/); assert.match(html, /href="\/article\/42"/)
})
