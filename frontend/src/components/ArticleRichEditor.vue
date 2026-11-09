<template>
  <div class="article-rich-editor-host" :style="fullscreen ? { height: `${placeholderHeight}px` } : undefined">
    <Teleport to="body" :disabled="!fullscreen">
    <ElFocusTrap :trapped="fullscreen" :loop="fullscreen" :focus-trap-el="editorRoot" @focus-after-trapped="focusFullscreenBody" @release-requested="exitFullscreen">
    <div ref="editorRoot" class="article-rich-editor" :class="{ 'is-fullscreen': fullscreen, 'has-side-panel': sidePanelOpen, 'is-document': layout === 'document', 'has-editor-headings': headingCount > 0 }"
      :role="fullscreen ? 'dialog' : undefined" :aria-modal="fullscreen ? true : undefined"
      :aria-label="fullscreen ? '全屏编辑正文' : undefined" :tabindex="fullscreen ? -1 : undefined"
      :style="{ '--article-editor-height': height || '560px', '--writing-ai-width': `${sidePanelWidth || 424}px` }">
    <div v-if="fullscreen" class="fullscreen-bar">
      <span>全屏写作 <small>编辑正文</small></span>
      <slot name="fullscreen-actions" />
      <button type="button" :disabled="leavingFullscreen" @click="exitFullscreen">退出全屏 <kbd>Esc</kbd></button>
    </div>
    <Toolbar class="toolbar" :editor="editorRef" :defaultConfig="toolbarConfig" mode="default" />
    <EditorTableOfContents v-if="editorRef && (layout === 'document' || fullscreen)" :editor="editorRef" :root="editorRoot"
      :document-layout="layout === 'document'" :fullscreen="fullscreen" :side-panel-open="sidePanelOpen" @headings-change="headingCount = $event" />
    <Editor class="editor" :style="{ height: fullscreen ? '0px' : layout === 'document' ? 'auto' : 'var(--article-editor-height)' }" :model-value="normalizedHtml" :defaultConfig="editorConfig" mode="default"
      @update:model-value="$emit('update:modelValue', $event)" @onCreated="handleCreated" />
    <EditorBlockHandle v-if="editorRef" :editor="editorRef" :root="editorRoot" :fullscreen="fullscreen" />
    <div class="writing-reference-lines" aria-hidden="true"><span v-for="(line, index) in referenceLines" :key="index" :data-reference-id="line.id" :style="line.style"></span></div>
    <div v-if="slashOpen" class="slash-menu" :style="slashPosition" role="listbox" aria-label="插入块">
      <div class="slash-menu-hint">输入搜索 · ↑↓ 选择 · Enter 插入</div>
      <button v-for="(command, index) in filteredCommands" :key="command.type" type="button" role="option" :aria-selected="slashIndex === index" :class="{active: slashIndex === index}" @mousedown.prevent @click.stop="executeSlash(command.type)">{{ command.label }}</button>
      <div v-if="!filteredCommands.length" class="slash-menu-hint">没有匹配的块，Esc 关闭</div>
    </div>
    <slot name="side-panel" />
    </div>
    </ElFocusTrap>
    </Teleport>
  </div>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ElFocusTrap from 'element-plus/es/components/focus-trap/index.mjs'
import '@/utils/editorHighlighting'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import { Boot, DomEditor, SlateEditor, SlateRange, SlateTransforms, SlateElement, SlateText, type IDomEditor } from '@wangeditor/editor'
import { editorReplacementHtml, type EditorProposal, type EditOutcome } from '@/utils/editorTools'
import EditorBlockHandle from './EditorBlockHandle.vue'
import EditorTableOfContents from './EditorTableOfContents.vue'
import { installEditorClipboard } from '@/utils/editorClipboard'
import { indentPixels, normalizeEditorIndents } from '@/utils/articleTextStyle'
import { blockDepth, indentOutline, registerEditorOutline } from '@/utils/editorOutline'
import request from '@/utils/request'
import { blockStyleMenuKey, registerArticleBlockStyle } from '@/utils/editorBlockStyle'
import { bindEditorReference, editorReferenceMenuKey, registerEditorReferenceMenu } from '@/utils/editorReferenceMenu'
registerArticleBlockStyle()
registerEditorOutline()
registerEditorReferenceMenu()
const props = defineProps<{ modelValue: string; layout?: 'document' | 'contained'; height?: string; sidePanelOpen?: boolean; sidePanelWidth?: number; aiReference?: boolean }>()
const normalizedHtml = computed(() => normalizeEditorIndents(props.modelValue))
const emit = defineEmits<{ 'update:modelValue': [value: string]; ready: [html: string]; fullscreenChange: [value: boolean]; quoteSelection: [text: string] }>()
const editorRef = shallowRef<IDomEditor>()
const editorRoot = ref<HTMLElement>()
const fullscreen = ref(false), leavingFullscreen = ref(false), placeholderHeight = ref(0)
const headingCount = ref(0)
let restoreBackground: (() => void) | undefined
let releaseReferenceMenu: (() => void) | undefined
let disposed = false
let selectedRange: SlateRange | null = null
type Operation = Parameters<IDomEditor['apply']>[0]
type TrackedRange = ReturnType<typeof SlateEditor.rangeRef>
const snapshots = new Map<string, { bodyHtml: string | null; selection: string; fragment: string; range: TrackedRange | null }>()
const undoRecords = new Map<string, { version: number; batch: Operation[] }>()
let contentVersion = 0
// Presentation only: range refs follow Slate edits; no marks enter saved HTML or undo history.
const referenceRanges = new Map<string, { text: string; range: TrackedRange }>()
const referenceLines = ref<{ id: string; style: Record<string, string> }[]>([])
let referenceFrame = 0, referenceObserver: ResizeObserver | undefined
function releaseReference(id: string) { referenceRanges.get(id)?.range.unref(); referenceRanges.delete(id) }
function markReference(id: string, text: string) {
  const editor = editorRef.value
  captureSelection()
  if (!editor || disposed || !selectedRange || !text) return
  try {
    if (SlateEditor.string(editor, selectedRange) !== text) return
    releaseReference(id)
    referenceRanges.set(id, { text, range: SlateEditor.rangeRef(editor, selectedRange, { affinity: 'inward' }) })
    if (referenceRanges.size > 32) releaseReference(referenceRanges.keys().next().value!)
    scheduleReferenceLines()
  } catch { /* Never guess a location by searching duplicate text. */ }
}
function syncReferenceMarkers(ids: string[]) {
  const retained = new Set(ids)
  for (const id of referenceRanges.keys()) if (!retained.has(id)) releaseReference(id)
  scheduleReferenceLines()
}
function scheduleReferenceLines() {
  if (disposed || referenceFrame) return
  referenceFrame = requestAnimationFrame(() => {
    referenceFrame = 0
    const editor = editorRef.value, root = editorRoot.value
    const scroll = root?.querySelector('.w-e-scroll')
    if (!editor || !root || !scroll) return
    const origin = root.getBoundingClientRect(), clip = scroll.getBoundingClientRect()
    const lines: typeof referenceLines.value = []
    for (const [id, reference] of referenceRanges) {
      const range = reference.range.current
      try {
        if (!range || SlateRange.isCollapsed(range) || SlateEditor.string(editor, range) !== reference.text) { releaseReference(id); continue }
        for (const rect of DomEditor.toDOMRange(editor, range).getClientRects()) {
          const left = Math.max(rect.left, clip.left), right = Math.min(rect.right, clip.right), bottom = rect.bottom - 1
          if (right <= left || !rect.height || bottom < clip.top || bottom > clip.bottom) continue
          lines.push({ id, style: { left: `${left - origin.left - root.clientLeft}px`, top: `${bottom - origin.top - root.clientTop}px`, width: `${right - left}px` } })
        }
      } catch { releaseReference(id) }
    }
    referenceLines.value = lines
  })
}
watch(() => [props.modelValue, props.sidePanelOpen, fullscreen.value], () => nextTick(scheduleReferenceLines), { flush: 'post' })
export interface EditorRead { html: string; text: string; selection: string; range: SlateRange | null }
function captureSelection() {
  const editor = editorRef.value, selection = document.getSelection()
  if (!editor || !selection?.anchorNode || !editorRoot.value?.querySelector('[data-slate-editor]')?.contains(selection.anchorNode)) return
  const range = DomEditor.toSlateRange(editor, selection, { exactMatch: true, suppressThrow: true })
  selectedRange = range && !SlateRange.isCollapsed(range) ? structuredClone(range) : null
}
function readDocument(): EditorRead {
  const editor = editorRef.value
  if (!editor || disposed) throw new Error('编辑器还未准备好')
  let selection = ''
  try { if (selectedRange) selection = SlateEditor.string(editor, selectedRange) } catch { selectedRange = null }
  return { html: editor.getHtml(), text: editor.getText(), selection, range: selectedRange ? structuredClone(selectedRange) : null }
}
function releaseSnapshot(id: string) {
  snapshots.get(id)?.range?.unref()
  snapshots.delete(id)
}
function clearSnapshots() {
  for (const id of snapshots.keys()) releaseSnapshot(id)
  undoRecords.clear()
}
function captureSnapshot(id: string, source: EditorRead) {
  const editor = editorRef.value
  if (!editor || disposed) return
  releaseSnapshot(id)
  let range: TrackedRange | null = null, fragment = ''
  try {
    if (source.range && source.selection && source.selection.length <= 12000 && SlateEditor.string(editor, source.range) === source.selection) {
      fragment = JSON.stringify(SlateEditor.fragment(editor, source.range))
      // Bound retained rich fragments, including selections containing images.
      if (fragment.length <= 128000) range = SlateEditor.rangeRef(editor, source.range, { affinity: 'inward' })
      else fragment = ''
    }
  } catch { /* An unavailable selection cannot authorize a replacement. */ }
  // Long bodies cannot be replaced as a whole, so do not retain their full HTML.
  snapshots.set(id, { bodyHtml: source.html.length <= 32000 ? source.html : null, selection: range ? source.selection : '', fragment: range ? fragment : '', range })
  if (snapshots.size > 8) releaseSnapshot(snapshots.keys().next().value!)
}
function applyProposal(proposal: EditorProposal, snapshotId: string): EditOutcome {
  const editor = editorRef.value
  if (!editor || disposed || editor.isDisabled()) return { ok: false, message: '当前正文不可编辑' }
  const snapshot = snapshots.get(snapshotId)
  if (!snapshot) return { ok: false, message: '编辑快照已失效，请重新生成修改建议' }
  let targetRange: SlateRange | null = null
  if (proposal.target === 'selection') {
    const current = snapshot.range?.current
    if (!current || SlateRange.isCollapsed(current)) return { ok: false, message: '原选区已删除或无法定位，请重新选择并生成建议' }
    try {
      if (snapshot.selection !== proposal.before || SlateEditor.string(editor, current) !== proposal.before
          || JSON.stringify(SlateEditor.fragment(editor, current)) !== snapshot.fragment) {
        return { ok: false, message: '原选区的文字或格式已变化，请重新选择并生成建议' }
      }
      targetRange = structuredClone(current)
    } catch { return { ok: false, message: '原选区无法定位，请重新选择并生成建议' } }
  } else if (proposal.target === 'body') {
    if (snapshot.bodyHtml === null || editor.getHtml() !== snapshot.bodyHtml) return { ok: false, message: '正文已在生成建议后发生变化，请重新生成，避免覆盖新内容' }
  } else return { ok: false, message: '正文编辑器不处理标题修改' }
  // Roll back to the current document, which may contain unrelated user edits.
  const beforeHtml = editor.getHtml()
  const originalApply = editor.apply
  const history = (editor as IDomEditor & { history: { undos: Operation[][]; redos: Operation[][] } }).history
  const previousUndos = history.undos.map(batch => [...batch]), previousRedos = history.redos.map(batch => [...batch])
  const operations: Operation[] = []
  // wangEditor bundles its own Slate history module. Group the actual editor's
  // operations, retaining every earlier undo entry, into one explicit batch.
  editor.apply = operation => {
    if (operation.type !== 'set_selection') operations.push(operation)
    originalApply(operation)
  }
  const groupHistory = () => { history.undos = operations.length ? [...previousUndos, operations].slice(-100) : previousUndos; history.redos = operations.length ? [] : previousRedos }
  try {
    if (proposal.target === 'selection') {
      SlateTransforms.select(editor, targetRange!)
      SlateEditor.withoutNormalizing(editor, () => SlateTransforms.insertText(editor, proposal.after))
    } else if (proposal.target === 'body') {
      editor.setHtml(editorReplacementHtml(proposal.after, proposal.citations))
    } else return { ok: false, message: '正文编辑器不处理标题修改' }
    selectedRange = null
    groupHistory()
    undoRecords.set(proposal.id, { version: contentVersion, batch: operations })
    if (undoRecords.size > 8) undoRecords.delete(undoRecords.keys().next().value!)
    emit('update:modelValue', editor.getHtml())
    return { ok: true, message: '已应用到正文，可用撤销恢复' }
  } catch {
    editor.apply = originalApply
    editor.setHtml(beforeHtml)
    history.undos = previousUndos
    history.redos = previousRedos
    return { ok: false, message: '未能应用修改，已保留原文，请重新生成' }
  } finally { editor.apply = originalApply }
}
function undoProposal(proposalId: string): EditOutcome {
  const editor = editorRef.value
  const undo = undoRecords.get(proposalId)
  if (!editor || disposed || editor.isDisabled() || !undo || contentVersion !== undo.version) return { ok: false, message: '正文已继续修改，请使用编辑器的撤销按钮逐步恢复' }
  const history = (editor as IDomEditor & { history: { undos: Operation[][] } }).history
  if (history.undos.at(-1) !== undo.batch) return { ok: false, message: '撤销记录已变化，请使用编辑器的撤销按钮逐步恢复' }
  editor.undo()
  undoRecords.delete(proposalId)
  emit('update:modelValue', editor.getHtml())
  return { ok: true, message: '已撤销本次正文修改' }
}
defineExpose({ resetHistory, focusStart, readDocument, captureSnapshot, releaseSnapshot, clearSnapshots, applyProposal, undoProposal, markReference, syncReferenceMarkers })
function resetHistory() {
  const editor = editorRef.value
  if (!editor) return
  const history = (editor as IDomEditor & { history: { undos: Operation[][]; redos: Operation[][] } }).history
  history.undos = []; history.redos = []
  clearSnapshots()
  selectedRange = null
  slashOpen.value = false
}
function isCommandParagraph(node: unknown) {
  return SlateElement.isElement(node) && DomEditor.getNodeType(node) === 'paragraph' && node.children.every(child => SlateText.isText(child))
}
function focusStart() {
  const editor = editorRef.value
  if (!editor || editor.isDisabled()) return
  editor.focus()
  SlateTransforms.select(editor, SlateEditor.start(editor, []))
}
const commands = [
  {type:'paragraph',label:'正文',search:'text paragraph'},
  {type:'header1',label:'一级标题 H1',search:'heading h1'},
  {type:'header2',label:'二级标题 H2',search:'heading h2'},
  {type:'header3',label:'三级标题 H3',search:'heading h3'},
  {type:'bullet',label:'无序列表',search:'bullet list'},
  {type:'ordered',label:'有序列表',search:'number list'},
  {type:'todo',label:'待办列表',search:'todo task'},
  {type:'blockquote',label:'引用',search:'quote'},
  {type:'pre',label:'代码块',search:'code'},
  {type:'divider',label:'分隔线',search:'divider hr'},
]
const slashOpen = ref(false), slashQuery = ref(''), slashIndex = ref(0)
const slashPosition = ref<Record<string,string>>({})
watch(() => props.modelValue, () => { if (slashOpen.value) void nextTick(refreshSlash) })
const filteredCommands = computed(() => commands.filter(command => `${command.label} ${command.search}`.toLowerCase().includes(slashQuery.value.toLowerCase())))
let slashRange: SlateRange | null = null, releaseDocumentKeys: (() => void) | undefined
let composing = false, dismissedSlash = ''
function refreshSlash() {
  try { refreshSlashState() } catch { slashOpen.value = false; slashRange = null }
}
function refreshSlashState() {
  const editor = editorRef.value
  if (!editor || composing || editor.isDisabled() || !editor.selection || !SlateRange.isCollapsed(editor.selection)) { slashOpen.value = false; return }
  const entry = SlateEditor.above(editor, {match: node => DomEditor.getNodeType(node) === 'paragraph'})
  if (!entry || entry[1].length !== 1 || !isCommandParagraph(entry[0])) { slashOpen.value = false; return }
  const range = {anchor: SlateEditor.start(editor, entry[1]), focus: editor.selection.anchor}
  const text = SlateEditor.string(editor, range)
  if (!/^\/[^\n/]{0,32}$/.test(text) || SlateEditor.string(editor, entry[1]) !== text) { slashOpen.value = false; dismissedSlash = ''; return }
  const signature = JSON.stringify(range) + text
  if (signature === dismissedSlash) { slashOpen.value = false; return }
  slashRange = structuredClone(range)
  if (slashQuery.value !== text.slice(1)) slashIndex.value = 0
  slashQuery.value = text.slice(1)
  const rect = DomEditor.toDOMRange(editor, editor.selection).getBoundingClientRect()
  const width = Math.min(280, window.innerWidth - 24), height = Math.min(360, window.innerHeight - 24)
  slashPosition.value = {left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`, top: `${Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - height - 12))}px`, width: `${width}px`, maxHeight: `${height}px`}
  slashOpen.value = true
}
function executeSlash(type: string) {
  const editor = editorRef.value, range = slashRange
  if (!editor || !range || !slashOpen.value) return
  // Verify the original command before a mouse operation restores its selection.
  const path = [range.anchor.path[0]!]
  try {
    const block = SlateEditor.node(editor, path)[0]
    if (SlateEditor.string(editor, range) !== '/' + slashQuery.value || !isCommandParagraph(block) || SlateEditor.string(editor, path) !== '/' + slashQuery.value) { slashOpen.value = false; return }
  } catch { slashOpen.value = false; return }
  const history = (editor as IDomEditor & {history:{undos:Operation[][];redos:Operation[][]}}).history
  const previous = history.undos.map(batch => [...batch]), operations: Operation[] = [], apply = editor.apply
  editor.apply = operation => { if (operation.type !== 'set_selection') operations.push(operation); apply(operation) }
  try {
    editor.focus()
    SlateTransforms.select(editor, range)
    SlateEditor.withoutNormalizing(editor, () => {
      SlateTransforms.delete(editor)
      if (type === 'pre' || type === 'divider') {
        SlateTransforms.removeNodes(editor, {at:path})
        const node = type === 'pre' ? {type:'pre',children:[{type:'code',language:'',children:[{text:''}]}]} : {type:'divider',children:[{text:''}]}
        SlateTransforms.insertNodes(editor, node, {at:path})
        if (type === 'divider') {
          const after = [path[0]! + 1]
          SlateTransforms.insertNodes(editor, {type:'paragraph',children:[{text:''}]}, {at:after})
          SlateTransforms.select(editor, SlateEditor.start(editor, after))
        } else SlateTransforms.select(editor, SlateEditor.start(editor, path))
      } else {
        SlateTransforms.setNodes(editor, {type: ['bullet','ordered'].includes(type) ? 'list-item' : type, ordered:type === 'ordered' ? true : type === 'bullet' ? false : undefined, level: ['bullet','ordered'].includes(type) ? 0 : undefined, checked:type === 'todo' ? false : undefined} as any, {at:path})
        SlateTransforms.select(editor, SlateEditor.start(editor, path))
      }
    })
    history.undos = [...previous, operations].slice(-100)
    history.redos = []
  } finally { editor.apply = apply; slashOpen.value = false; slashRange = null }
}
function clearTypingMarks(editor: IDomEditor) {
  const entry = SlateEditor.above(editor, { match: node => SlateElement.isElement(node) && SlateEditor.isBlock(editor, node) })
  if (entry && !SlateEditor.string(editor, entry[1])) {
    for (const [leaf, path] of SlateEditor.nodes(editor, { at: entry[1], match: SlateText.isText })) {
      const keys = Object.keys(leaf).filter(key => key !== 'text')
      if (keys.length) SlateTransforms.unsetNodes(editor, keys, { at: path })
    }
  }
  editor.marks = null
}
function indentCode(editor: IDomEditor, path: number[], backwards: boolean) {
  const selection = editor.selection!
  const start = SlateEditor.start(editor, path), text = SlateEditor.string(editor, path)
  const [from, to] = SlateRange.edges(selection)
  const fromOffset = SlateEditor.string(editor, { anchor: start, focus: from }).length
  const toOffset = SlateEditor.string(editor, { anchor: start, focus: to }).length
  const firstLine = fromOffset ? text.lastIndexOf('\n', fromOffset - 1) + 1 : 0
  const changes: { at: number; remove: number }[] = []
  if (SlateRange.isCollapsed(selection) && !backwards) {
    SlateTransforms.insertText(editor, '  ')
    return
  }
  let offset = firstLine
  do {
    const spaces = text.slice(offset).match(/^ {1,2}/)?.[0].length || 0
    if (!backwards || spaces) changes.push({ at: offset, remove: backwards ? spaces : 0 })
    const next = text.indexOf('\n', offset)
    if (next < 0 || next + 1 >= toOffset) break
    offset = next + 1
  } while (offset <= toOffset)
  const tracked = SlateEditor.rangeRef(editor, selection, { affinity: 'inward' })
  try {
    SlateEditor.withoutNormalizing(editor, () => {
      for (const change of changes.reverse()) {
        const point = change.at ? SlateEditor.after(editor, start, { distance: change.at, unit: 'offset' })! : start
        if (change.remove) {
          const end = SlateEditor.after(editor, point, { distance: change.remove, unit: 'offset' })!
          SlateTransforms.delete(editor, { at: { anchor: point, focus: end } })
        } else SlateTransforms.insertText(editor, '  ', { at: point })
      }
    })
    if (tracked.current) SlateTransforms.select(editor, tracked.current)
  } finally { tracked.unref() }
}
function handleIndent(editor: IDomEditor, backwards: boolean): boolean {
  if (!editor.selection || editor.isDisabled()) return false
  // Cells own Tab navigation. Never indent a paragraph nested inside a table.
  const cell = SlateEditor.above(editor, { match: node => ['table-cell', 'table', 'table-row'].includes(DomEditor.getNodeType(node)) })
  if (cell) return false
  const code = SlateEditor.above(editor, { match: node => DomEditor.getNodeType(node) === 'code' })
  if (code) { indentCode(editor, code[1], backwards); return true }
  const outcome = indentOutline(editor, backwards)
  if (outcome.handled) {
    if (outcome.limited) ElMessage({ type: 'info', message: '当前内容块已达最大缩进层级', grouping: true })
    return true
  }
  const blocks = [...SlateEditor.nodes(editor, { match: node => SlateElement.isElement(node)
    && /^(list-item|todo)$/.test(DomEditor.getNodeType(node)), mode: 'highest' })]
    .filter(([, path]) => path.length === 1)
  if (!blocks.length) return false
  SlateEditor.withoutNormalizing(editor, () => {
    for (const [node, path] of blocks) {
      const block = node as SlateElement & { type: string; indent?: string; level?: number }
      if (block.type === 'list-item') {
        const level = Math.max(0, Math.min(8, (block.level || 0) + (backwards ? -1 : 1)))
        SlateTransforms.setNodes(editor, backwards && !block.level
          ? { type: 'paragraph', level: undefined, ordered: undefined } as any : { level } as any, { at: path })
      } else SlateTransforms.setNodes(editor, { indent: backwards ? undefined : '32px' } as any, { at: path })
    }
  })
  return true
}
function decreaseIndentAtStart(editor: IDomEditor): boolean {
  const selection = editor.selection
  if (!selection || !SlateRange.isCollapsed(selection)) return false
  const entry = SlateEditor.above(editor, { match: node => SlateElement.isElement(node)
    && /^(paragraph|header[1-6]|list-item|todo|blockquote)$/.test(DomEditor.getNodeType(node)) })
  if (!entry || entry[1].length !== 1 || !SlateEditor.isStart(editor, selection.anchor, entry[1])) return false
  const node = entry[0] as SlateElement & { indent?: string; level?: number }
  const hasIndent = DomEditor.getNodeType(node) === 'list-item' ? (node.level || 0) > 0 : (indentPixels(node.indent || '') ?? 0) > 0 || blockDepth(node) > 0
  return hasIndent && handleIndent(editor, true)
}
function installDocumentKeys(editor: IDomEditor) {
  const root = editorRoot.value!
  const inBody = (event: Event) => event.target instanceof Element && !!event.target.closest('[data-slate-editor]')
  const onInput = (event: Event) => { if (inBody(event)) void nextTick(refreshSlash) }
  const onStart = (event: Event) => { if (inBody(event)) { composing = true; slashOpen.value = false } }
  const onEnd = (event: Event) => { if (inBody(event)) { composing = false; void nextTick(refreshSlash) } }
  const syncDomSelection = () => {
    const selection = document.getSelection()
    if (selection?.anchorNode && root.querySelector('[data-slate-editor]')?.contains(selection.anchorNode)) {
      const range = DomEditor.toSlateRange(editor, selection, { exactMatch: true, suppressThrow: true })
      if (range && (!editor.selection || !SlateRange.equals(editor.selection, range))) SlateTransforms.select(editor, range)
    }
  }
  const onClipboard = (event: Event) => { if (inBody(event) && !composing) syncDomSelection() }
  const onBeforeInput = (event: Event) => {
    const input = event as InputEvent
    if (!inBody(event) || input.inputType !== 'deleteContentBackward' || input.isComposing || composing || editor.isDisabled()) return
    syncDomSelection()
    if (decreaseIndentAtStart(editor)) { event.preventDefault(); event.stopPropagation(); slashOpen.value = false }
  }
  const onKey = (event: KeyboardEvent) => {
    if (!inBody(event)) return
    if (event.isComposing || composing || event.keyCode === 229 || editor.isDisabled()) return
    // The DOM selection listener is throttled. Enter/Tab immediately after a
    // click must use the caret the user sees, rather than the previous block.
    if (['Enter','Tab','Backspace'].includes(event.key)) syncDomSelection()
    if (event.key === 'Backspace' && !event.ctrlKey && !event.metaKey && !event.altKey && decreaseIndentAtStart(editor)) {
      event.preventDefault(); event.stopPropagation(); slashOpen.value = false
      return
    }
    if (event.key === 'Tab' && !event.ctrlKey && !event.metaKey && !event.altKey && handleIndent(editor, event.shiftKey)) {
      event.preventDefault(); event.stopPropagation(); slashOpen.value = false
      return
    }
    if (slashOpen.value && ['ArrowUp','ArrowDown','Enter','Escape'].includes(event.key) && !(event.key === 'Enter' && event.shiftKey)) {
      event.preventDefault(); event.stopPropagation()
      if (event.key === 'Escape') { dismissedSlash = JSON.stringify(slashRange) + '/' + slashQuery.value; slashOpen.value = false }
      else if (event.key === 'Enter') { const command = filteredCommands.value[slashIndex.value]; if (command) executeSlash(command.type) }
      else { const count = filteredCommands.value.length; slashIndex.value = count ? (slashIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + count) % count : 0; void nextTick(() => root.querySelector('.slash-menu button.active')?.scrollIntoView({block:'nearest'})) }
      return
    }
    if (event.key === 'Enter' && event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && editor.selection) {
      const block = SlateEditor.above(editor, {match: node => /^(paragraph|header[1-6]|list-item|todo|blockquote)$/.test(DomEditor.getNodeType(node))})
      if (block && block[1].length === 1) {
        event.preventDefault(); event.stopPropagation(); slashOpen.value = false
        SlateTransforms.insertText(editor, '\n')
        return
      }
    }
    if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey || !editor.selection || !SlateRange.isCollapsed(editor.selection)) return
    const emptyBlock = SlateEditor.above(editor, {match: node => ['list-item', 'todo', 'blockquote'].includes(DomEditor.getNodeType(node))})
    if (emptyBlock && emptyBlock[1].length === 1 && SlateElement.isElement(emptyBlock[0]) && emptyBlock[0].children.every(child => SlateText.isText(child)) && !SlateEditor.string(editor, emptyBlock[1])) {
      event.preventDefault(); event.stopPropagation()
      SlateTransforms.setNodes(editor, {type:'paragraph', ordered:undefined, level:undefined, checked:undefined} as any, {at:emptyBlock[1]})
      return
    }
    const entry = SlateEditor.above(editor, {match: node => /^(header[1-6]|paragraph|blockquote)$/.test(DomEditor.getNodeType(node))})
    if (!entry || entry[1].length !== 1) return
    if (SlateEditor.isStart(editor, editor.selection.anchor, entry[1]) && SlateEditor.string(editor, entry[1])) {
      event.preventDefault(); event.stopPropagation()
      const caret = SlateEditor.pointRef(editor, editor.selection.anchor, { affinity: 'forward' })
      SlateTransforms.insertNodes(editor, { type: 'paragraph', blockIndent: blockDepth(entry[0]) || undefined, children: [{ text: '' }] } as any, { at: entry[1] })
      if (caret.current) SlateTransforms.select(editor, caret.current)
      caret.unref()
      return
    }
    const depth = blockDepth(entry[0]), heading = /^header[1-6]$/.test(DomEditor.getNodeType(entry[0]))
    // Authored indents do not define a movable subtree. Split at the caret;
    // never skip the following paragraphs based on their visual offsets.
    if (!heading || !SlateEditor.isEnd(editor, editor.selection.anchor, entry[1])) return
    event.preventDefault(); event.stopPropagation()
    SlateEditor.withoutNormalizing(editor, () => {
      if (SlateEditor.string(editor, entry[1])) editor.insertBreak()
      SlateTransforms.setNodes(editor, {type:'paragraph', indent:undefined, blockIndent:depth || undefined, textAlign:undefined, lineHeight:undefined, blockFontSize:undefined} as any)
      clearTypingMarks(editor)
    })
  }
  const onSelection = () => {
    if (!slashOpen.value || !slashRange) return
    const selection = document.getSelection()
    if (!selection?.anchorNode || !root.querySelector('[data-slate-editor]')?.contains(selection.anchorNode)) { slashOpen.value = false; return }
    const range = DomEditor.toSlateRange(editor, selection, {exactMatch:true,suppressThrow:true})
    if (!range || JSON.stringify(range.focus) !== JSON.stringify(slashRange.focus) || !SlateRange.isCollapsed(range)) slashOpen.value = false
  }
  const onOutside = (event: Event) => {
    if (!inBody(event) && !(event.target instanceof Element && event.target.closest('.slash-menu'))) slashOpen.value = false
  }
  document.addEventListener('pointerdown', onOutside)
  document.addEventListener('focusin', onOutside)
  document.addEventListener('selectionchange', onSelection)
  const reposition = (event: Event) => { if (event.target instanceof Element && event.target.closest('.slash-menu')) return; if (slashOpen.value) slashOpen.value = false }
  // wangEditor throttles DOM selections and toolbar state by 200ms. A quick
  // paragraph → grouped menu click must format the current caret immediately.
  const syncToolbarSelection = (event: Event) => {
    if (!(event.target instanceof Element) || !event.target.closest('.toolbar')) return
    const selection = document.getSelection()
    if (!selection?.anchorNode || !root.querySelector('[data-slate-editor]')?.contains(selection.anchorNode)) return
    const range = DomEditor.toSlateRange(editor, selection, {exactMatch:true,suppressThrow:true})
    if (range && (!editor.selection || !SlateRange.equals(editor.selection, range))) SlateTransforms.select(editor, range)
    const toolbar = DomEditor.getToolbar(editor)
    toolbar?.changeToolbarState()
    toolbar?.changeToolbarState.flush?.()
  }
  root.addEventListener('mousedown', syncToolbarSelection, true)
  root.addEventListener('keydown', onKey, true)
  root.addEventListener('paste', onClipboard, true)
  root.addEventListener('copy', onClipboard, true)
  root.addEventListener('cut', onClipboard, true)
  root.addEventListener('beforeinput', onBeforeInput, true)
  root.addEventListener('input', onInput)
  root.addEventListener('keyup', onInput)
  root.addEventListener('compositionstart', onStart)
  root.addEventListener('compositionend', onEnd)
  window.addEventListener('scroll', reposition, true)
  window.addEventListener('resize', reposition)
  releaseDocumentKeys = () => {
    document.removeEventListener('pointerdown', onOutside)
    document.removeEventListener('focusin', onOutside)
    document.removeEventListener('selectionchange', onSelection)
    root.removeEventListener('mousedown', syncToolbarSelection, true)
    root.removeEventListener('keydown', onKey, true); root.removeEventListener('input', onInput); root.removeEventListener('keyup', onInput)
    root.removeEventListener('paste', onClipboard, true)
    root.removeEventListener('copy', onClipboard, true)
    root.removeEventListener('cut', onClipboard, true)
    root.removeEventListener('beforeinput', onBeforeInput, true)
    root.removeEventListener('compositionstart', onStart); root.removeEventListener('compositionend', onEnd)
    window.removeEventListener('scroll', reposition, true); window.removeEventListener('resize', reposition)
  }
}

document.addEventListener('selectionchange', captureSelection)
const toolbarConfig = { toolbarKeys: [
  blockStyleMenuKey, '|', 'bold', 'italic', 'insertLink', '|', 'bulletedList', 'numberedList',
  { key: 'group-insert', title: '插入', menuKeys: ['uploadImage', 'insertTable', 'todo', 'blockquote', 'codeBlock', 'divider'] },
  { key: 'group-more', title: '更多', menuKeys: ['italic', 'insertLink', 'numberedList', 'underline', 'through', 'color', 'bgColor', 'fontSize', 'lineHeight', 'clearStyle'] },
  '|', 'undo', 'redo', 'fullScreen',
] }
const editorConfig = {
  placeholder: '开始写作，输入 / 插入内容…',
  hoverbarKeys: {
    ...Boot.editorConfig.hoverbarKeys,
    text: { menuKeys: [blockStyleMenuKey, 'insertLink', 'bulletedList', '|', 'bold', 'through', 'color', 'bgColor', 'clearStyle', ...(props.aiReference ? ['|', editorReferenceMenuKey] : [])] },
  },
  MENU_CONF: {
    uploadImage: {
      maxFileSize: 15 * 1024 * 1024, allowedFileTypes: ['image/*'],
      async customUpload(file: File, insertFn: (url: string, alt: string, href: string) => void) {
        const form = new FormData()
        form.append('file', file)
        try {
          const res = await request.post('/file/upload-article-image', form, { headers: { 'Content-Type': 'multipart/form-data' } })
          if (res.code !== 200 || !res.data?.url) throw new Error(res.message || '图片上传失败')
          if (!disposed) insertFn(res.data.url, '', res.data.url)
        } catch (error) { ElMessage.error(error instanceof Error ? error.message : '图片上传失败') }
      },
    },
    codeSelectLang: { codeLangs: [
      { text: 'Java', value: 'java' }, { text: 'JavaScript', value: 'javascript' },
      { text: 'TypeScript', value: 'typescript' }, { text: 'Python', value: 'python' },
      { text: 'Go', value: 'go' }, { text: 'C/C++', value: 'cpp' }, { text: 'SQL', value: 'sql' },
      { text: 'HTML', value: 'html' }, { text: 'CSS', value: 'css' }, { text: 'Shell', value: 'bash' },
      { text: 'JSON', value: 'json' }, { text: 'XML', value: 'xml' },
    ] },
  },
}
function handleCreated(editor: IDomEditor) {
  if (disposed) { editor.destroy(); return }
  editorRef.value = editor
  installEditorClipboard(editor)
  // Pasted legacy HTML must normalize through Slate operations, preserving
  // the paste undo transaction and tracked AI ranges instead of resetting HTML.
  const normalizeNode = editor.normalizeNode
  editor.normalizeNode = entry => {
    const [node, path] = entry
    const value = (node as { indent?: unknown }).indent
    if (SlateElement.isElement(node) && typeof value === 'string' && /em$/i.test(value)) {
      const pixels = indentPixels(value)
      if (pixels !== null) { SlateTransforms.setNodes(editor, { indent: `${pixels}px` } as any, { at: path }); return }
    }
    normalizeNode(entry)
  }
  if (props.aiReference) {
    window.addEventListener('scroll', scheduleReferenceLines, true)
    window.addEventListener('resize', scheduleReferenceLines)
    if (typeof ResizeObserver !== 'undefined') {
      referenceObserver = new ResizeObserver(scheduleReferenceLines)
      if (editorRoot.value) referenceObserver.observe(editorRoot.value)
      const content = editorRoot.value?.querySelector('[data-slate-editor]')
      if (content) referenceObserver.observe(content)
    }
    void document.fonts?.ready.then(scheduleReferenceLines)
  }
  if (props.aiReference) releaseReferenceMenu = bindEditorReference(editor, () => selectedRange, (text, range) => {
    if (disposed) return
    if (text.length > 12000) { ElMessage.info('选中文字较长，请缩小到 12000 字以内'); return }
    selectedRange = range
    emit('quoteSelection', text)
  })
  installDocumentKeys(editor)
  const apply = editor.apply
  editor.apply = operation => {
    if (operation.type !== 'set_selection') contentVersion += 1
    apply(operation)
    if (operation.type !== 'set_selection' && referenceRanges.size) void nextTick(scheduleReferenceLines)
  }
  const enterFullscreen = editor.fullScreen.bind(editor)
  editor.fullScreen = () => {
    if (disposed || editor.isFullScreen) return
    placeholderHeight.value = editorRoot.value?.getBoundingClientRect().height || 0
    enterFullscreen()
  }
  editor.on('fullScreen', onFullscreen)
  editor.on('unFullScreen', onUnFullscreen)
  const html = editor.getHtml()
  emit('update:modelValue', html)
  resetHistory()
  emit('ready', html)
}
function focusFullscreenBody(event: Event) {
  event.preventDefault()
  // Do not schedule a later autofocus that can steal a freshly clicked caret.
  const body = editorRoot.value?.querySelector('[data-slate-editor]')
  if (!body?.contains(document.activeElement)) editorRef.value?.focus()
}
async function onFullscreen() {
  if (disposed) return
  fullscreen.value = true
  emit('fullscreenChange', true)
  await nextTick()
  if (disposed || !fullscreen.value || restoreBackground) return
  // Keep the same editor instance/undo history, but move it above page/dialog
  // stacking contexts. The nested focus trap pauses an enclosing draft dialog.
  const root = editorRoot.value!
  const siblings = [...document.body.children].filter((node): node is HTMLElement => node instanceof HTMLElement && node !== root && !node.contains(root))
  const inert = siblings.map(node => [node, node.inert] as const)
  const overflow = [document.body, document.documentElement].map(node => ({ node, value: node.style.getPropertyValue('overflow'), priority: node.style.getPropertyPriority('overflow') }))
  inert.forEach(([node]) => { node.inert = true })
  overflow.forEach(({ node }) => node.style.setProperty('overflow', 'hidden'))
  restoreBackground = () => {
    inert.forEach(([node, value]) => { node.inert = value })
    overflow.forEach(({ node, value, priority }) => value ? node.style.setProperty('overflow', value, priority) : node.style.removeProperty('overflow'))
  }
}
function exitFullscreen(event?: Event) {
  event?.preventDefault()
  event?.stopPropagation()
  if (!fullscreen.value || leavingFullscreen.value || !editorRef.value || disposed) return
  leavingFullscreen.value = true
  editorRef.value.unFullScreen()
}
function onUnFullscreen() {
  if (disposed) return
  restoreBackground?.()
  restoreBackground = undefined
  fullscreen.value = false
  emit('fullscreenChange', false)
  leavingFullscreen.value = false
  nextTick(() => editorRoot.value?.querySelector<HTMLButtonElement>('[data-menu-key="fullScreen"]')?.focus({ preventScroll: true }))
}
onBeforeUnmount(() => {
  disposed = true
  releaseDocumentKeys?.()
  releaseReferenceMenu?.()
  clearSnapshots()
  for (const id of referenceRanges.keys()) releaseReference(id)
  cancelAnimationFrame(referenceFrame)
  referenceObserver?.disconnect()
  window.removeEventListener('scroll', scheduleReferenceLines, true)
  window.removeEventListener('resize', scheduleReferenceLines)
  document.removeEventListener('selectionchange', captureSelection)
  editorRef.value?.off('fullScreen', onFullscreen)
  editorRef.value?.off('unFullScreen', onUnFullscreen)
  restoreBackground?.()
  restoreBackground = undefined
})
// Toolbar is a child and may access the editor while it unmounts.
onUnmounted(() => {
  const editor = editorRef.value
  if (!editor) return
  // wangEditor 5.1 leaves a trailing throttled selection callback on close.
  // Cancel it before destroy removes the editor from its internal WeakMap.
  const textarea = DomEditor.getTextarea(editor) as unknown as { onDOMSelectionChange?: { cancel?: () => void } }
  textarea.onDOMSelectionChange?.cancel?.()
  editor.destroy()
  editorRef.value = undefined
})
</script>
<style scoped>
.article-rich-editor-host{min-width:0}
.article-rich-editor{position:relative}
.writing-reference-lines{position:absolute;inset:0;pointer-events:none;z-index:2;overflow:hidden;border-radius:inherit}
.writing-reference-lines span{position:absolute;height:0;border-bottom:2px solid #86a728;box-shadow:0 1px 0 #d0ff4550}
.article-rich-editor{--w-e-toolbar-bg-color:var(--ej-surface,#fffdf7);--w-e-textarea-bg-color:var(--ej-surface,#fffdf7);--w-e-toolbar-color:#333;--w-e-toolbar-active-color:#111;--w-e-toolbar-active-bg-color:#e8f6be;--w-e-toolbar-border-color:#e5e3dc;border:1px solid var(--ej-line,#dedbd2);border-radius:14px;background:var(--ej-surface,#fffdf7);min-width:0}
/* The editor's own .w-e-scroll owns scrolling. Clipping its wrapper hides
   upward-opening selection menus behind the toolbar. */
.toolbar{border-bottom:1px solid var(--ej-line,#dedbd2);border-radius:14px 14px 0 0}.editor{height:var(--article-editor-height);border-radius:0 0 14px 14px}
:deep(.w-e-text-container),:deep(.w-e-scroll){border-radius:0 0 14px 14px}:deep(.w-e-hover-bar){z-index:550}
:deep(.w-e-hover-bar [data-menu-key="articleAiReference"]){color:var(--ej-ink,#171714);font-weight:650;background:var(--studio-lime-soft,#edf8cb);white-space:nowrap}
:deep(.w-e-hover-bar [data-menu-key="articleAiReference"]:hover){background:var(--studio-lime,#d0ff45)}
@media(max-width:767px){:deep(.w-e-hover-bar){max-width:calc(100vw - 24px);flex-wrap:wrap}}
:deep(.w-e-text-container){font-size:16px;line-height:1.8}:deep(.w-e-scroll){padding:8px}:deep(img){max-width:100%;height:auto}:deep(pre){max-width:100%;overflow-x:auto}
.article-rich-editor.is-fullscreen{position:fixed;inset:0;z-index:4000;display:flex;flex-direction:column;width:100%;height:100dvh!important;max-height:none;max-width:none;margin:0;border:0;border-radius:0;box-sizing:border-box;isolation:isolate;background:var(--ej-surface,#fffdf7);color:var(--ej-ink,#171717)}
.is-fullscreen .toolbar{flex:none;border-radius:0}.is-fullscreen .editor{flex:1;min-height:0;border-radius:0}.is-fullscreen :deep(.w-e-text-container),.is-fullscreen :deep(.w-e-scroll){border-radius:0}.is-fullscreen :deep([data-slate-editor]){max-width:none;margin:0;padding:0 16px 24px}
/* The outline and writing surface occupy different grid cells. Neither scrolling
   nor the paragraph handle can turn the outline into part of the editable page. */
@media(min-width:1000px){
  .article-rich-editor.is-fullscreen{--fullscreen-toc-width:80px;display:grid;grid-template-columns:var(--fullscreen-toc-width) minmax(0,1fr);grid-template-rows:auto auto minmax(0,1fr);grid-template-areas:"header header" "outline toolbar" "outline body"}
  .article-rich-editor.is-fullscreen.has-editor-headings{--fullscreen-toc-width:clamp(184px,17vw,256px)}
  .is-fullscreen .fullscreen-bar{grid-area:header}
  .is-fullscreen > .editor-toc{grid-area:outline}
  .is-fullscreen > .toolbar{grid-area:toolbar;min-width:0}
  .is-fullscreen > .editor{grid-area:body;min-width:0;height:100%!important}
  .is-fullscreen > :deep(.block-handle-ui){position:absolute}
}
.fullscreen-bar{display:flex;flex:none;align-items:center;justify-content:space-between;gap:12px;padding:12px max(16px,env(safe-area-inset-right)) 12px max(16px,env(safe-area-inset-left));border-bottom:1px solid var(--ej-line,#dedbd2);background:var(--ej-surface,#fffdf7);font-size:14px;font-weight:700}.fullscreen-bar small{margin-left:10px;color:var(--ej-muted,#777);font-size:12px;font-weight:400}.fullscreen-bar button{display:flex;align-items:center;gap:10px;flex-shrink:0;padding:8px 16px;border:1px solid #171717;border-radius:999px;background:var(--studio-lime,#cbff46);color:#171717;font:inherit;font-size:13px;cursor:pointer}.fullscreen-bar button:focus-visible{outline:2px solid currentColor;outline-offset:3px}.fullscreen-bar kbd{font:inherit;font-size:11px;font-weight:400;opacity:.7}
@media(max-width:600px){:deep(.w-e-bar){gap:0}:deep(.w-e-bar-item){padding:2px}:deep(.w-e-scroll){padding:4px}}
.fullscreen-bar > span{margin-right:auto}
@media(min-width:1600px){.article-rich-editor.is-fullscreen.has-side-panel{grid-template-columns:var(--fullscreen-toc-width) minmax(0,1fr) calc(var(--writing-ai-width,424px) + 32px);grid-template-areas:"header header header" "outline toolbar ." "outline body ."}}
@media(min-width:1200px) and (max-width:1599px){
  .article-rich-editor.is-fullscreen.has-side-panel{display:flex}
  .is-fullscreen.has-side-panel > .toolbar,.is-fullscreen.has-side-panel > .editor,.is-fullscreen.has-side-panel > .editor-toc{margin-right:calc(var(--writing-ai-width,424px) + 32px)}
}
@media(max-width:480px){.fullscreen-bar{gap:8px}.fullscreen-bar small{display:none}.fullscreen-bar button{padding:8px 12px}}

.is-document:not(.is-fullscreen){border:0}
.is-document:not(.is-fullscreen) .toolbar{position:sticky;top:var(--document-toolbar-top,136px);z-index:25;border:1px solid var(--ej-line,#dedbd2);border-radius:8px;background:var(--ej-surface,#fffdf7)}
.toolbar :deep(.w-e-bar){flex-wrap:nowrap;overflow:visible}
.is-document:not(.is-fullscreen) .editor{height:auto!important;min-height:65vh}
.is-document:not(.is-fullscreen) :deep(.w-e-scroll){height:auto!important;min-height:65vh;overflow:visible!important}
.is-document:not(.is-fullscreen) :deep(.w-e-text-container){height:auto!important;overflow:visible!important}
:deep([data-slate-editor]){scroll-margin-top:130px;padding-left:48px!important}
:deep(.w-e-text-placeholder){left:48px}
.slash-menu{position:fixed;z-index:4100;overflow:auto;padding:6px;border:1px solid var(--ej-line,#dedbd2);border-radius:12px;background:var(--ej-surface,#fffdf7);box-shadow:0 10px 36px #0002;box-sizing:border-box}
.slash-menu button{display:block;width:100%;border:0;background:transparent;text-align:left;padding:8px 12px;border-radius:6px;color:var(--ej-ink,#171714);cursor:pointer}
.slash-menu button.active,.slash-menu button:hover{background:var(--studio-lime-soft,#edf8cb)}
.slash-menu-hint{padding:7px 10px;font-size:11px;color:var(--ej-muted,#777)}
@media(max-width:767px){.is-document:not(.is-fullscreen) .toolbar{top:var(--document-toolbar-top,172px)}}

@media(max-width:767px){.toolbar :deep(.w-e-bar-item){padding:0}.toolbar :deep(.w-e-bar-item button){min-width:24px;padding:3px}.toolbar :deep(.w-e-bar-item .select-button){width:66px}.toolbar :deep(.w-e-bar-item > button[data-menu-key="insertLink"]),.toolbar :deep(.w-e-bar-item > button[data-menu-key="italic"]),.toolbar :deep(.w-e-bar-item > button[data-menu-key="numberedList"]){display:none}}
@media(max-width:360px){.toolbar :deep(.w-e-bar){flex-wrap:wrap}}

</style>
