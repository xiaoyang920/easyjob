import { test } from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
globalThis.window = new JSDOM('').window
const { safeHtml } = await import('../src/utils/safeHtml.ts')

test('model HTML cannot execute scripts, handlers, SVG or unsafe URLs', () => {
  const html = safeHtml('<script>x()</script><svg onload="x()"></svg><img src="/uploads/a.jpg" onerror="x()"><a href="javascript:x()">x</a><iframe srcdoc="x"></iframe><p style="background:url(https://evil.example/x)">text</p>')
  assert.doesNotMatch(html, /script|onerror|onload|javascript:|iframe|<svg|style=/)
  assert.match(html, /src="\/uploads\/a.jpg"/)
})
test('normal Markdown, code, tables and citation links survive', () => {
  const html = safeHtml('<pre class="streaming-table"><code class="language-java">a &lt; b</code></pre><table><tr><td>cell</td></tr></table><a href="/article/42" class="citation-link">[1]</a>')
  assert.match(html, /language-java/); assert.match(html, /<table>/); assert.match(html, /href="\/article\/42"/)
})

test('only bounded first-line indents survive article display and draft round trips', () => {
  const html = safeHtml('<p style="text-indent: 2em;">正文</p><h2 style="text-indent:4em">标题</h2><p style="text-indent:999em">x</p><p style="text-indent:2em;background:url(https://evil.example/a)">y</p><img style="text-indent:2em" src="/a.png"><p style="position:fixed">z</p>')
  assert.match(html, /style="text-indent: 32px;"/)
  assert.match(html, /style="text-indent: 64px;"/)
  assert.doesNotMatch(html, /999|background|position|evil\.example|<img style=/)
  assert.equal(safeHtml(html), html)
})

test('toolbar text formats survive while CSS layout and external resources are discarded', () => {
  const html = safeHtml('<p style="text-indent:64px;line-height:2;text-align:center;position:fixed"><span style="font-size:32px;color:rgb(30, 60, 90);background-color:#ffeeaa;background-image:url(https://evil.example/x)"><strong><s>格式文字</s></strong></span></p>')
  assert.match(html, /text-indent: 64px;/); assert.match(html, /line-height: 2;/); assert.match(html, /text-align: center;/)
  assert.match(html, /font-size: 32px;/); assert.match(html, /color: rgb\(30, 60, 90\);/); assert.match(html, /background-color: #ffeeaa;/)
  assert.match(html, /<strong><s>格式文字<\/s><\/strong>/)
  assert.doesNotMatch(html, /position|background-image|evil\.example/)
  assert.equal(safeHtml(html), html)
})
