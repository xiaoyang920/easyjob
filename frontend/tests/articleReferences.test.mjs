import test from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { articleReferenceText, selectedArticleReference } from '../src/utils/articleReferences.ts'
import { writingMessage, readWritingMessage, referenceLabel } from '../src/utils/writingReferences.ts'

test('published article references keep paragraphs and code indentation without reader controls or DOM changes', () => {
  const dom = new JSDOM('<main><h2>标题</h2><p>第一段<br>下一行</p><pre><div class="article-code-toolbar">go 复制代码 放大查看</div><code>if ok {\n  run()\n}</code></pre><img src="/uploads/example.png"></main>')
  const root = dom.window.document.querySelector('main'), before = root.innerHTML
  assert.equal(articleReferenceText(root), '标题\n第一段\n下一行\nif ok {\n  run()\n}')
  assert.equal(root.innerHTML, before)
})

test('selected references retain their exact occurrence, reject outside selections and enforce the text bound', () => {
  const dom = new JSDOM(`<main><p>同样的文字</p><p>同样的文字</p><p>${'字'.repeat(12001)}</p></main><aside>外部文字</aside>`)
  const root = dom.window.document.querySelector('main'), selection = dom.window.getSelection()
  const range = dom.window.document.createRange(), second = root.querySelectorAll('p')[1].firstChild
  range.selectNodeContents(second); selection.addRange(range)
  const reference = selectedArticleReference(root, selection)
  assert.equal(reference.text, '同样的文字')
  assert.equal(reference.range.startContainer, second)
  range.selectNodeContents(dom.window.document.querySelector('aside')); selection.removeAllRanges(); selection.addRange(range)
  assert.equal(selectedArticleReference(root, selection), undefined)
  range.selectNodeContents(root.querySelectorAll('p')[2]); selection.removeAllRanges(); selection.addRange(range)
  assert.equal(selectedArticleReference(root, selection), undefined)
})

test('article quotes use the bounded reference/history contract and their own display label', () => {
  const reference = { kind: 'article', text: '标题：已发布文章\n正文：公开内容', truncated: false }
  assert.equal(referenceLabel('article'), '当前文章')
  assert.deepEqual(readWritingMessage(writingMessage('解释当前文章', reference)), { content: '解释当前文章', reference })
})
