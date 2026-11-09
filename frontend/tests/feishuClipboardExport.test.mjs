import { test } from 'node:test'
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'
import { feishuClipboardRecord, appendFeishuClipboardRecord } from '../src/utils/feishuClipboardExport.ts'

const block = (text, depth = 0, indent = '0px') => ({ type: 'paragraph', blockIndent: depth, indent, children: [{ text }] })
const records = value => Object.values(value.recordMap).filter(record => record.snapshot.type !== 'page')

test('outbound copy carries editable headings, structural depth and independent first-line formatting', () => {
  const source = [{ ...block('标题'), type: 'header2' }, block('第一行', 1, '32px'), block('第二行', 2), block('第三行', 1), block('尾段')]
  const before = structuredClone(source), result = JSON.parse(feishuClipboardRecord(source))
  const nodes = records(result)
  assert.deepEqual(nodes.map(node => node.snapshot.type), ['heading2', 'text', 'text', 'text', 'text'])
  assert.equal(nodes[1].snapshot.parent_id, nodes[0].id)
  assert.equal(nodes[2].snapshot.parent_id, nodes[1].id)
  assert.equal(nodes[3].snapshot.parent_id, nodes[0].id)
  assert.equal(nodes[4].snapshot.parent_id, result.rootId)
  assert.deepEqual(result.recordIds, [nodes[0].id, nodes[4].id])
  assert.deepEqual(nodes.map(node => node.snapshot.text_indent), [0, 1, 0, 0, 0])
  assert.deepEqual(source, before)
})

test('rich text attribution preserves marks, links, UTF-16 offsets and soft line breaks', () => {
  const result = JSON.parse(feishuClipboardRecord([{ type: 'paragraph', children: [
    { text: '中文😀\n第二行', bold: true, italic: true },
    { type: 'link', url: 'https://example.org/a?q=中文', children: [{ text: '链接', underline: true }] },
    { text: '删除', through: true }, { text: '代码', code: true },
  ] }]))
  const rich = records(result)[0].snapshot.text, value = rich.initialAttributedTexts
  assert.equal(value.text['0'], '中文😀\n第二行链接删除代码')
  assert.match(value.attribs['0'], /^\*0\*1\|1\+5\*0\*1\+3/)
  assert.deepEqual(Object.values(rich.apool.numToAttrib), [
    ['bold', 'true'], ['italic', 'true'], ['link', encodeURIComponent('https://example.org/a?q=中文')],
    ['underline', 'true'], ['strikethrough', 'true'], ['inlineCode', 'true'],
  ])
  assert.equal(rich.apool.nextNum, 6)
})

test('a partial inline selection does not impose its source heading or paragraph indentation', () => {
  const source = { ...block('选中的词', 2, '32px'), type: 'header1' }
  const result = JSON.parse(feishuClipboardRecord([source], true)), node = records(result)[0]
  assert.equal(node.snapshot.type, 'text')
  assert.equal(node.snapshot.parent_id, result.rootId)
  assert.equal(node.snapshot.text_indent, 0)
  assert.equal(node.snapshot.text.initialAttributedTexts.text['0'], '选中的词')
})

test('unsupported media and structures retain the complete HTML path, with no partial record', () => {
  for (const node of [
    { type: 'table', children: [] }, { type: 'pre', children: [] }, { type: 'blockquote', children: [{ text: '引用' }] },
    { type: 'paragraph', children: [{ type: 'image', src: '/uploads/picture.png', children: [{ text: '' }] }] },
  ]) assert.equal(feishuClipboardRecord([block('保留前文'), node]), null)
  assert.equal(feishuClipboardRecord([block('非法距离', 0, '9999px')]), null)
})

test('copying a subtree omits unselected ancestors and maps legacy first-line distances to the native option', () => {
  const result = JSON.parse(feishuClipboardRecord([block('选中的父块', 2, '64px'), block('选中的子块', 3, '16px'), block('回到根层')]))
  const nodes = records(result)
  assert.equal(nodes[0].snapshot.parent_id, result.rootId)
  assert.equal(nodes[1].snapshot.parent_id, nodes[0].id)
  assert.equal(nodes[2].snapshot.parent_id, result.rootId)
  assert.deepEqual(nodes.map(node => node.snapshot.text_indent), [1, 1, 0])
})

test('HTML fallback is hidden and escaped, and neither payload includes source identities', () => {
  const dom = new JSDOM(''), container = dom.window.document.createElement('div')
  globalThis.document = dom.window.document
  const result = feishuClipboardRecord([{ ...block('文字"<&\n后续'), id: 'private-source-id', author: 'private-source-author' }])
  container.innerHTML = '<p>原始 HTML</p>'
  appendFeishuClipboardRecord(container, result)
  const metadata = container.querySelector('[data-lark-record-data]')
  assert.equal(metadata.hidden, true)
  assert.equal(metadata.getAttribute('data-lark-record-data'), result)
  assert.equal(metadata.getAttribute('data-lark-record-format'), 'docx/record')
  assert.equal(container.children[0].outerHTML, '<p>原始 HTML</p>')
  assert.doesNotMatch(result, /private-source|author|cookie|token/i)
  assert.doesNotMatch(container.innerHTML, /<script/i)
})
