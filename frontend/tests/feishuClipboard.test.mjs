import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('')
Object.assign(globalThis, {window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,NodeFilter:dom.window.NodeFilter})
const { feishuClipboardHtml } = await import('../src/utils/feishuClipboard.ts')
const fixture = JSON.parse(readFileSync(new URL('../tests-e2e/fixtures/feishu-outline-clipboard.json',import.meta.url),'utf8'))
const websiteReturn = JSON.parse(readFileSync(new URL('../tests-e2e/fixtures/feishu-website-return.json',import.meta.url),'utf8'))
const parse = data => {
  const result = document.createElement('div')
  result.innerHTML = feishuClipboardHtml({getData:type=>data[type] || ''}) || ''
  return result
}

test('actual Feishu clipboard flattens its tree once, preserving headings and structural offsets', () => {
  const result = parse(fixture)
  assert.equal(result.children.length,8)
  assert.deepEqual([...result.children].map(node=>node.textContent),['源标题','第一行正文','第二行正文','源末尾说明','源标题','第一行正文','第二行正文','源末尾说明'])
  assert.deepEqual([...result.children].map(node=>node.style.marginLeft),['','','','','32px','32px','32px','32px'])
  assert.equal(result.querySelector('h1').style.fontSize,'')
  assert.equal(result.querySelector('h1 span').style.fontSize,'')
  assert.equal(result.querySelector('p span').style.fontSize,'')
  assert.equal(result.querySelector('p').style.lineHeight,'1.625')
  assert.doesNotMatch(result.innerHTML,/data-lark|old-record|recordMap|author-|&nbsp;/)
})

test('actual website-to-Feishu-to-website copy retains heading parents, nested paragraphs and rich marks', () => {
  const result = parse(websiteReturn)
  assert.deepEqual([...result.children].slice(0,5).map(node=>node.tagName), ['H1','H2','P','P','P'])
  assert.deepEqual([...result.children].slice(0,5).map(node=>node.textContent), ['网站复制到飞书验证','二级标题','正文第一行','正文第二行','正文第三行'])
  assert.deepEqual([...result.children].slice(0,5).map(node=>node.style.marginLeft), ['', '32px', '64px', '96px', '64px'])
  assert.equal(result.children[3].style.textIndent, '32px')
  assert.equal(result.querySelector('a').getAttribute('href'), 'https://example.org/guide')
  assert.equal(result.querySelector('strong').textContent, '粗体')
})

test('semantic headings retain website defaults while explicitly authored sizes survive', () => {
  const result = parse({'text/html':'<div data-lark-html-role="root"><h1 class="ace-line">默认一级标题</h1><h1 class="ace-line" style="font-size:48px"><span style="font-size:48px">手工字号</span></h1></div>'})
  assert.doesNotMatch(result.children[0].outerHTML,/font-size/)
  assert.equal(result.children[1].style.fontSize,'48px')
  assert.equal(result.children[1].querySelector('span').style.fontSize,'48px')
})

test('HTML metadata fallback and the HTML-only portable outline keep the same nesting', () => {
  const metadata = document.createElement('span')
  metadata.setAttribute('data-lark-record-data',fixture['docx/record'])
  const expected = parse(fixture).innerHTML
  assert.equal(parse({'text/html':fixture['text/html']+metadata.outerHTML}).innerHTML,expected)
  const format = result => [...result.children].map(node=>({tag:node.tagName,text:node.textContent,depth:node.style.marginLeft,indent:node.style.textIndent||'0px'}))
  assert.deepEqual(format(parse({'text/html':fixture['text/html']})),format(parse(fixture)))
})

test('source first-line indent stays separate from depth, and does not leak into children', () => {
  const data = {...fixture}, record = JSON.parse(data['docx/record'])
  record.recordMap.b3.snapshot.text_indent = 1
  data['docx/record'] = JSON.stringify(record)
  data['text/html'] = data['text/html'].replace('class="ace-line ace-line old-record-id-b3"','style="text-indent:2em" class="ace-line text-indent old-record-id-b3"')
  const result = parse(data)
  assert.equal(result.children[3].style.textIndent,'32px')
  for (const child of [...result.children].slice(4)) assert.ok(['','0px'].includes(child.style.textIndent))
})

test('native marks, CSS marks, font sizes, color, links and images survive without active markup', () => {
  const result = parse({'text/html':'<div data-lark-html-role="root"><h3 class="ace-line" style="text-align:center"><span style="font-size:32px;color:rgb(30,60,90);background-color:#ffeeaa;font-weight:700;font-style:italic;text-decoration:underline line-through;position:fixed"><a href="https://example.org">格式</a></span><img src="/uploads/sample.png" onerror="evil()"><a href="javascript:evil()">恶意链接</a><script>evil()</script></h3></div>'})
  assert.equal(result.querySelector('h3').style.textAlign,'center')
  assert.equal(result.querySelector('span[style*="32px"]').style.color,'rgb(30, 60, 90)')
  assert.ok(result.querySelector('a[href="https://example.org"] span strong em u s'))
  assert.equal(result.querySelector('img').getAttribute('src'),'/uploads/sample.png')
  assert.doesNotMatch(result.innerHTML,/script|onerror|javascript:|position|evil\(\)/)
})

test('lists, tables and code remain structural units, preserving code language and literal spacing', () => {
  const result = parse({'text/html':'<div data-lark-html-role="root"><ol><li>列表</li></ol><table><tbody><tr><td><strong>单元格</strong></td></tr></tbody></table><pre><code class="language-java">  int a = 1;</code></pre></div>'})
  assert.deepEqual([...result.children].map(node=>node.tagName),['OL','TABLE','PRE'])
  assert.equal(result.querySelector('code.language-java').textContent,'  int a = 1;')
  assert.ok(result.querySelector('td strong'))
})

test('ordinary clipboard HTML is untouched, and malformed/cyclic Feishu metadata falls back safely', () => {
  assert.equal(feishuClipboardHtml({getData:type=>type==='text/html'?'<p>普通</p>':''}),null)
  const record = JSON.parse(fixture['docx/record'])
  record.recordMap.b4.snapshot.parent_id = 'b4'
  assert.equal(parse({...fixture,'docx/record':JSON.stringify(record)}).children[4].style.marginLeft,'32px')
  assert.equal(parse({...fixture,'docx/record':'{bad'}).children[4].style.marginLeft,'32px')
})
