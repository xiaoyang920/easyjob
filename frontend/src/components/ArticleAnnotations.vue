<template>
  <Teleport to="body">
    <button v-if="selectionQuote" type="button" class="quote-selection-action" :style="actionStyle" @pointerdown.prevent @click="startComment">
      <span aria-hidden="true">＋</span> 评论所选内容
    </button>
    <div v-if="openPanel && narrow" class="annotation-backdrop" @click="close" @wheel.prevent @touchmove.prevent></div>
    <section v-if="openPanel" ref="panel" class="annotation-panel" role="dialog" aria-label="划词评论" :aria-modal="narrow ? true : undefined" :style="panelStyle" @keydown="panelKeydown">
      <header class="annotation-header"><div><h2>划词评论 <span>{{ focusedIds ? focusedIds.length : total }}</span></h2><p>围绕原文交流，点击引用可查看位置</p></div><button ref="closeButton" type="button" aria-label="关闭划词评论" @click="close">×</button></header>
      <div v-if="focusedIds" class="annotation-scope"><span>这一处的评论 · {{ focusedIds.length }}</span><button type="button" @click="showAll">查看全部评论</button></div>
      <div class="annotation-content" :aria-busy="loading">
        <p v-if="markerError" class="annotation-notice" role="status">{{ markerError }} <button type="button" @click="loadMarkers">重试标记</button></p>
        <p v-if="notice" class="annotation-notice" role="status">{{ notice }}</p>
        <div v-if="error" class="annotation-empty" role="alert"><p>{{ error }}</p><button type="button" @click="refresh">重新加载</button></div>
        <p v-else-if="loading && !comments.length" class="annotation-empty">正在读取评论…</p>
        <div v-else-if="!comments.length" class="annotation-empty"><span class="empty-quote" aria-hidden="true">“</span><strong>从一句话开始讨论</strong><p>选中正文中的文字，再点击“评论所选内容”。</p></div>
        <article v-for="comment in comments" :key="comment.commentId" class="annotation-thread" :class="{ active: activeThread === comment.commentId }">
          <CommentQuotePreview :quote="comment.quote" @locate="locate" />
          <div class="annotation-author"><img :src="avatarUrl(comment.userAvatar, comment.userNickName)" alt="" @error="onAvatarError($event, comment.userNickName)" /><a :href="`/user-space/${comment.userId}`">{{ comment.userNickName }}</a><time>{{ comment.createTime }}</time></div>
          <p class="annotation-text">{{ comment.content }}</p>
          <div class="annotation-actions"><button type="button" :aria-expanded="activeThread === comment.commentId" @click="toggleThread(comment)">{{ activeThread === comment.commentId ? '收起回复' : `回复${comment.replyCount ? ` · ${comment.replyCount}` : ''}` }}</button><button v-if="String(comment.userId) === myUserId" type="button" @click="askDelete(comment)">删除</button></div>
          <div v-if="activeThread === comment.commentId" class="annotation-replies">
            <p v-if="replyLoading">正在读取回复…</p>
            <p v-if="replyError" role="alert">{{ replyError }} <button type="button" @click="loadReplies(comment)">重试</button></p>
            <div v-for="reply in replies" :key="reply.commentId" class="annotation-reply"><a :href="`/user-space/${reply.userId}`">{{ reply.userNickName }}</a><p>{{ reply.content }}</p></div>
            <button v-if="moreReplies" type="button" :disabled="replyLoading" @click="loadReplies(comment, true)">更多回复</button>
            <label class="sr-only" :for="`quote-reply-${comment.commentId}`">回复这条划词评论</label>
            <textarea :id="`quote-reply-${comment.commentId}`" v-model="replyText" maxlength="500" rows="2" placeholder="围绕这段原文说说你的看法…"></textarea>
            <div class="annotation-submit-row"><small>{{ replyText.length }}/500</small><button type="button" class="annotation-primary" :disabled="!replyText.trim() || submitting" @click="submitReply(comment)">{{ submitting ? '发布中…' : '发布回复' }}</button></div>
          </div>
        </article>
        <button v-if="hasMore" class="annotation-load-more" type="button" :disabled="loading" @click="load(true)">{{ loading ? '读取中…' : '更多划词评论' }}</button>
      </div>
      <form v-if="pendingQuote" class="annotation-composer" @submit.prevent="submit">
        <div class="composer-label"><strong>评论所选内容</strong><button type="button" :disabled="submitting" @click="cancelDraft">取消</button></div>
        <CommentQuotePreview :quote="pendingQuote" @locate="locate" />
        <label for="annotation-comment" class="sr-only">评论内容</label>
        <textarea id="annotation-comment" ref="composer" v-model="text" maxlength="500" rows="3" placeholder="你的疑问、补充或想法…"></textarea>
        <p v-if="submitError" class="annotation-error" role="alert">{{ submitError }}</p>
        <div class="annotation-submit-row"><small>{{ text.length }}/500</small><button type="submit" class="annotation-primary" :disabled="!text.trim() || submitting">{{ submitting ? '发布中…' : '发布评论' }}</button></div>
      </form>
      <footer v-else class="annotation-footer">选中正文任意文字，即可发起新讨论。</footer>
    </section>
    <div class="annotation-highlight-fallback" aria-hidden="true"><span v-for="(rect, i) in fallbackRects" :key="i" :style="rect"></span></div>
    <div class="article-comment-lines" aria-hidden="true"><span v-for="(line, i) in lineStyles" :key="i" class="article-comment-line" :style="line"></span></div>
    <el-dialog v-model="deleteOpen" title="删除这条评论？" width="min(400px, calc(100% - 32px))" class="ej-dialog" append-to-body :close-on-click-modal="false"><p>这条评论及其回复会一并删除。</p><template #footer><button type="button" class="annotation-dialog-button" @click="deleteOpen = false">取消</button><button type="button" class="annotation-dialog-button annotation-primary" :disabled="submitting" @click="remove">确认删除</button></template></el-dialog>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import request from '@/utils/request'
import { errorMessage, notify } from '@/utils/feedback'
import { avatarUrl, onAvatarError } from '@/utils/avatar'
import { latestRequest } from '@/utils/latestRequest'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'
import { selectedQuote, quoteRange, type CommentQuote } from '@/utils/commentAnchors'
import { groupCommentMarkers, markerBoxes, markerIdsAt, type QuoteMarker, type MarkerGroup, type MarkerBox } from '@/utils/commentMarkers'
import CommentQuotePreview from './CommentQuotePreview.vue'

interface Comment { commentId: string; userId: string; userNickName: string; userAvatar?: string; content: string; createTime: string; replyCount: number; quote?: CommentQuote }
const props = defineProps<{ articleId: string; articleAuthorId: string; root?: HTMLElement }>()
const emit = defineEmits<{ changed: []; login: []; opened: [] }>()
const openPanel = ref(false), narrow = ref(false), top = ref(88), panelHeight = ref(600), panel = ref<HTMLElement>(), closeButton = ref<HTMLButtonElement>(), composer = ref<HTMLTextAreaElement>()
const panelStyle = computed(() => ({ top: `${top.value}px`, ...(narrow.value ? { height: `${panelHeight.value}px`, bottom: 'auto' } : {}) }))
const selectionQuote = ref<CommentQuote>(), actionStyle = ref({ left: '0px', top: '0px' })
const pendingQuote = ref<CommentQuote>(), text = ref(''), submitError = ref(''), notice = ref('')
const comments = ref<Comment[]>([]), total = ref(0), page = ref(1), hasMore = ref(false), loading = ref(false), error = ref(''), submitting = ref(false)
const focusedIds = ref<string[]>(), markers = ref<QuoteMarker[]>([]), markerError = ref('')
const lineStyles = ref<Record<string,string>[]>([])
const activeThread = ref(''), replies = ref<Comment[]>([]), replyText = ref(''), replyError = ref(''), replyLoading = ref(false), replyPage = ref(1), moreReplies = ref(false)
const deleteOpen = ref(false), deleteTarget = ref<Comment>(), myUserId = ref(localStorage.getItem('userId') || '')
const reads = latestRequest(), replyReads = latestRequest(), markerReads = latestRequest()
const fallbackRects = ref<Record<string, string>[]>([])
let disposed = false, selectionFrame = 0, activeRange: Range | undefined, previousFocus: HTMLElement | undefined
let groups: MarkerGroup[] = [], boxes: MarkerBox[] = [], markerFrame = 0, rebuildPending = false
let boundRoot: HTMLElement | undefined, rootResize: ResizeObserver | undefined, rootMutation: MutationObserver | undefined
const highlights = () => (window as any).CSS?.highlights
function clearHighlight() { highlights()?.delete('easyjob-comment'); activeRange = undefined; fallbackRects.value = [] }
function paint(range: Range) {
  clearHighlight(); activeRange = range
  if (highlights() && (window as any).Highlight) highlights().set('easyjob-comment', new (window as any).Highlight(range))
  else updateFallback()
}
function updateFallback() {
  if (!activeRange || highlights()) return
  fallbackRects.value = Array.from(activeRange.getClientRects()).filter(r => r.width && r.height).map(r => ({ left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` }))
}
function layout() {
  narrow.value = innerWidth <= 760
  top.value = Math.max(12, (document.querySelector('.app-header')?.getBoundingClientRect().bottom || 64) + 12)
  panelHeight.value = Math.max(180, (visualViewport?.height || innerHeight) + (visualViewport?.offsetTop || 0) - top.value - 12)
  updateFallback()
  scheduleMarkers()
}
function scheduleMarkers(rebuild = false) {
  rebuildPending ||= rebuild
  cancelAnimationFrame(markerFrame)
  markerFrame = requestAnimationFrame(() => {
    if (!props.root || disposed) return
    if (rebuildPending) { groups = groupCommentMarkers(props.root, markers.value); rebuildPending = false }
    boxes = markerBoxes(props.root, groups, scrollX, scrollY)
    lineStyles.value = boxes.map(box => ({ left: `${box.left}px`, top: `${box.top + box.height - 1}px`, width: `${box.width}px` }))
  })
}
function articleScrolled(event: Event) {
  updateFallback()
  // Page scrolling does not change document coordinates. Inner code/table
  // scrolling does, and needs a new clipped geometry pass.
  if (event.target !== document && event.target !== window) scheduleMarkers()
}
function articlePointerMove(event: PointerEvent) {
  const ids = markerIdsAt(boxes, event.clientX + scrollX, event.clientY + scrollY)
  boundRoot?.classList.toggle('article-comment-hover', !!ids.length)
  if (ids.length) boundRoot?.setAttribute('title', `${ids.length} 条评论，点击查看`)
  else boundRoot?.removeAttribute('title')
}
function articlePointerLeave() { boundRoot?.classList.remove('article-comment-hover'); boundRoot?.removeAttribute('title') }
function articleClicked(event: MouseEvent) {
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || (event.target as Element).closest('a,button,input,textarea,select,img')) return
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed) return // Selecting/copying text is not opening a thread.
  const ids = markerIdsAt(boxes, event.clientX + scrollX, event.clientY + scrollY)
  if (!ids.length) return
  event.preventDefault()
  void openForMarkers(ids)
}
function bindRoot(root?: HTMLElement) {
  rootResize?.disconnect(); rootMutation?.disconnect()
  boundRoot?.removeEventListener('click', articleClicked); boundRoot?.removeEventListener('pointermove', articlePointerMove); boundRoot?.removeEventListener('pointerleave', articlePointerLeave)
  articlePointerLeave(); boundRoot = root
  if (!root) { groups = []; boxes = []; lineStyles.value = []; return }
  root.addEventListener('click', articleClicked); root.addEventListener('pointermove', articlePointerMove); root.addEventListener('pointerleave', articlePointerLeave)
  rootResize = new ResizeObserver(() => scheduleMarkers())
  rootResize.observe(root)
  rootMutation = new MutationObserver(() => scheduleMarkers(true))
  rootMutation.observe(root, { childList: true, subtree: true, characterData: true })
  scheduleMarkers(true)
}
function selectionChanged() {
  cancelAnimationFrame(selectionFrame)
  selectionFrame = requestAnimationFrame(() => {
    const selection = window.getSelection(), root = props.root
    selectionQuote.value = root ? selectedQuote(root, selection) : undefined
    if (!selectionQuote.value || !selection?.rangeCount) return
    const rect = selection.getRangeAt(0).getBoundingClientRect()
    if (rect.bottom < top.value || rect.top > innerHeight) { selectionQuote.value = undefined; return }
    actionStyle.value = { left: `${Math.max(12, Math.min(innerWidth - 170, rect.left + rect.width / 2 - 80))}px`, top: `${Math.max(top.value, Math.min(innerHeight - 48, rect.top - 44))}px` }
  })
}
async function open() {
  focusedIds.value = undefined
  previousFocus = document.activeElement as HTMLElement
  openPanel.value = true; emit('opened'); layout()
  await nextTick(); (pendingQuote.value ? composer.value : closeButton.value)?.focus()
  void load()
}
async function openForMarkers(ids: string[]) {
  focusedIds.value = [...ids].sort((a,b) => BigInt(a) > BigInt(b) ? -1 : 1)
  comments.value = []; activeThread.value = ''; replies.value = []; replyReads.cancel()
  previousFocus = document.activeElement as HTMLElement
  openPanel.value = true; emit('opened'); layout()
  const group = groups.find(group => group.ids.some(id => ids.includes(id)))
  if (group) paint(group.range)
  await nextTick(); closeButton.value?.focus({ preventScroll: true })
  await load()
}
async function showAll() { focusedIds.value = undefined; await load() }
function close() { openPanel.value = false; selectionQuote.value = undefined; clearHighlight(); previousFocus?.focus({ preventScroll: true }) }
function cancelDraft() { pendingQuote.value = undefined; text.value = ''; submitError.value = ''; clearHighlight() }
async function startComment() {
  if (!selectionQuote.value) return
  if (pendingQuote.value && text.value.trim()) { notify.warning('请先发布或取消正在编辑的评论'); return }
  pendingQuote.value = { ...selectionQuote.value }; submitError.value = ''; notice.value = ''
  const range = props.root && quoteRange(props.root, pendingQuote.value)
  if (range) paint(range)
  window.getSelection()?.removeAllRanges(); selectionQuote.value = undefined
  await open()
}
function locate(quote: CommentQuote) {
  const range = props.root && quoteRange(props.root, quote)
  if (!range) {
    clearHighlight(); notice.value = '原文已修改或位置无法确认，仍保留评论时引用的内容。'
    if (!openPanel.value) notify.warning(notice.value)
    return
  }
  notice.value = ''; paint(range)
  const rect = range.getBoundingClientRect()
  window.scrollTo({ top: Math.max(0, scrollY + rect.top - Math.max(top.value + 24, innerHeight * .32)), behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}
async function load(more = false) {
  const ticket = reads.begin(), nextPage = more ? page.value + 1 : 1
  loading.value = true; error.value = ''
  try {
    const subset = focusedIds.value?.slice((nextPage-1)*20,nextPage*20)
    if (subset && !subset.length) { comments.value = []; hasMore.value = false; return }
    const res = await request.get('/comment/quotes', { params: { articleId: props.articleId, page: subset ? 1 : nextPage, size: 20, ...(subset ? { ids: subset.join(',') } : {}) }, signal: ticket.signal })
    if (!ticket.isCurrent() || disposed) return
    const data = res.data
    if (!Array.isArray(data?.records)) throw new Error('划词评论数据暂不可用，请稍后重试')
    comments.value = more ? [...comments.value, ...data.records.filter((c: Comment) => !comments.value.some(old => old.commentId === c.commentId))] : data.records
    if (!focusedIds.value) total.value = data.total
    page.value = nextPage; hasMore.value = focusedIds.value ? nextPage*20 < focusedIds.value.length : data.current < data.pages
  } catch (err) { if (ticket.isCurrent() && !disposed) error.value = errorMessage(err, '划词评论暂时无法读取') }
  finally { if (ticket.isCurrent()) loading.value = false }
}
async function loadMarkers() {
  const ticket = markerReads.begin(), collected: QuoteMarker[] = [], seen = new Set<string>()
  let cursor = '0'
  markerError.value = ''
  try {
    do {
      const res = await request.get('/comment/quote-markers', { params: { articleId: props.articleId, afterId: cursor, size: 200 }, signal: ticket.signal })
      if (!ticket.isCurrent() || disposed) return
      if (!Array.isArray(res.data?.records)) throw new Error('正文评论标记暂不可用')
      collected.push(...res.data.records.filter((item: QuoteMarker) => {
        if (!/^\d+$/.test(item.commentId) || seen.has(item.commentId)) return false
        seen.add(item.commentId); return true
      }))
      const next = res.data.nextCursor || ''
      if (next && (!/^\d+$/.test(next) || BigInt(next) <= BigInt(cursor))) throw new Error('正文评论标记分页暂不可用')
      cursor = next
      // Render each batch so long articles do not wait for all metadata pages.
      markers.value = [...collected]; scheduleMarkers(true)
    } while (cursor)
    total.value = collected.length
    if (focusedIds.value) focusedIds.value = focusedIds.value.filter(id => seen.has(id))
  } catch (err) { if (ticket.isCurrent() && !disposed) markerError.value = errorMessage(err,'正文评论提示线暂不可用，可打开划词评论查看') }
}
async function refresh() { await loadMarkers(); if (!disposed) await load() }
async function submit() {
  if (!pendingQuote.value || !text.value.trim() || submitting.value) return
  if (!localStorage.getItem('token')) { emit('login'); return }
  myUserId.value = localStorage.getItem('userId') || ''
  submitting.value = true; submitError.value = ''
  try {
    await request.post('/comment/create', { articleId: props.articleId, articleUserId: props.articleAuthorId, content: text.value.trim(), quote: pendingQuote.value })
    if (disposed) return
    cancelDraft(); emit('changed'); await refresh(); notify.success('划词评论已发布')
  } catch (err) { if (!disposed) submitError.value = errorMessage(err, '发布失败，评论内容已保留，请重试') }
  finally { submitting.value = false }
}
async function toggleThread(comment: Comment) {
  if (activeThread.value === comment.commentId) { activeThread.value = ''; replyReads.cancel(); return }
  activeThread.value = comment.commentId; replies.value = []; replyText.value = ''; await loadReplies(comment)
}
async function loadReplies(comment: Comment, more = false) {
  const ticket = replyReads.begin(), nextPage = more ? replyPage.value + 1 : 1
  replyLoading.value = true; replyError.value = ''
  try {
    const res = await request.get('/comment/replies', { params: { commentId: comment.commentId, page: nextPage, size: 20 }, signal: ticket.signal })
    if (!ticket.isCurrent() || disposed || activeThread.value !== comment.commentId) return
    replies.value = more ? [...replies.value, ...res.data.records] : res.data.records
    replyPage.value = nextPage; moreReplies.value = res.data.current < res.data.pages
  } catch (err) { if (ticket.isCurrent() && !disposed) replyError.value = errorMessage(err, '回复读取失败') }
  finally { if (ticket.isCurrent()) replyLoading.value = false }
}
async function submitReply(comment: Comment) {
  if (!replyText.value.trim() || submitting.value) return
  if (!localStorage.getItem('token')) { emit('login'); return }
  submitting.value = true; replyError.value = ''
  try {
    await request.post('/comment/create', { articleId: props.articleId, articleUserId: props.articleAuthorId, parentId: comment.commentId, replyUserId: comment.userId, content: replyText.value.trim() })
    if (disposed) return
    if (activeThread.value === comment.commentId) { replyText.value = ''; await loadReplies(comment) }
    comment.replyCount++; emit('changed')
  } catch (err) { if (!disposed) replyError.value = errorMessage(err, '回复发布失败，输入已保留') }
  finally { submitting.value = false }
}
function askDelete(comment: Comment) { deleteTarget.value = comment; deleteOpen.value = true }
async function remove() {
  if (!deleteTarget.value || submitting.value) return
  submitting.value = true
  try {
    await request.delete(`/comment/${deleteTarget.value.commentId}`)
    if (disposed) return
    deleteOpen.value = false; clearHighlight(); emit('changed'); await refresh()
  } catch (err) { notify.error(errorMessage(err, '删除失败，请重试')) }
  finally { submitting.value = false }
}
function panelKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && !deleteOpen.value) { event.stopPropagation(); close() }
  if (event.key !== 'Tab' || !narrow.value) return
  const items = panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),a,textarea:not(:disabled)')
  const first = items?.[0], last = items?.[items.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(() => props.root, root => { selectionQuote.value = undefined; clearHighlight(); bindRoot(root) })
function authChanged() {
  const previous = myUserId.value
  myUserId.value = localStorage.getItem('userId') || ''
  if (!myUserId.value || (previous && previous !== myUserId.value)) { close(); cancelDraft(); replyText.value = ''; activeThread.value = '' }
}
onMounted(() => { bindRoot(props.root); layout(); void refresh(); document.addEventListener('selectionchange', selectionChanged); window.addEventListener('resize', layout); window.addEventListener('scroll', articleScrolled, true); visualViewport?.addEventListener('resize', layout); eventBus.on(EVENT_AUTH_CHANGED, authChanged); eventBus.on(EVENT_AUTH_EXPIRED, authChanged) })
onUnmounted(() => { disposed = true; reads.cancel(); replyReads.cancel(); markerReads.cancel(); cancelAnimationFrame(selectionFrame); cancelAnimationFrame(markerFrame); bindRoot(undefined); clearHighlight(); document.removeEventListener('selectionchange', selectionChanged); window.removeEventListener('resize', layout); window.removeEventListener('scroll', articleScrolled, true); visualViewport?.removeEventListener('resize', layout); eventBus.off(EVENT_AUTH_CHANGED, authChanged); eventBus.off(EVENT_AUTH_EXPIRED, authChanged) })
defineExpose({ open, locate, refresh, total })
</script>

<style>
::highlight(easyjob-comment) { background:#ffe6a2; color:inherit; }
.article-comment-lines { position:absolute; left:0; top:0; height:0; width:100%; z-index:20; pointer-events:none; }
.article-comment-line { position:absolute; height:2px; border-radius:2px; background:#e9b941; pointer-events:none; }
.article-content.article-comment-hover { cursor:pointer; }
.annotation-scope { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:10px 20px; background:#fff1bf; border-bottom:1px solid var(--ej-line); font-size:12px; }
.annotation-scope button { border:0; background:none; padding:4px 0; text-decoration:underline; }
.annotation-panel { position:fixed; right:20px; bottom:20px; width:380px; max-width:calc(100vw - 24px); z-index:2200; display:flex; flex-direction:column; background:var(--ej-surface,#fffdf7); color:var(--ej-ink,#171715); border:1px solid var(--ej-ink); border-radius:20px; box-shadow:6px 6px 0 #00000015; font-size:14px; }
.annotation-panel button,.annotation-dialog-button,.quote-selection-action { font:inherit; color:inherit; cursor:pointer; }
.annotation-panel button:disabled,.annotation-dialog-button:disabled { opacity:.45; cursor:not-allowed; }
.annotation-panel button:focus-visible,.annotation-dialog-button:focus-visible { outline:2px solid var(--ej-ink); outline-offset:3px; border-radius:5px; }
.annotation-panel .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.annotation-header { display:flex; align-items:flex-start; gap:12px; justify-content:space-between; padding:20px; border-bottom:1px solid var(--ej-line); flex-shrink:0; }
.annotation-header h2 { margin:0; font-size:18px; font-weight:750; }
.annotation-header h2 span { font-size:13px; border:1px solid var(--ej-ink); border-radius:99px; background:var(--studio-lime,#baff32); padding:1px 7px; margin-left:5px; }
.annotation-header p { margin:7px 0 0; font-size:12px; color:var(--ej-muted); }
.annotation-header > button { border:0; background:none; font-size:26px; line-height:1; padding:0 4px; }
.annotation-content { flex:1; min-height:0; overflow-y:auto; overscroll-behavior:contain; padding:16px; }
.annotation-thread { padding:14px; border:1px solid var(--ej-line); border-radius:14px; background:var(--ej-surface); margin-bottom:12px; }
.annotation-thread.active { border-color:var(--ej-ink); }
.annotation-thread > .comment-quote-preview { margin-top:0; }
.annotation-author { display:flex; gap:7px; align-items:center; margin-top:14px; font-size:12px; }
.annotation-author img { width:24px; height:24px; border-radius:50%; object-fit:cover; }
.annotation-panel a { color:var(--ej-ink); text-decoration:none; }
.annotation-author time { margin-left:auto; color:var(--ej-muted); font-size:10px; }
.annotation-text,.annotation-reply p { white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.75; margin:10px 0; }
.annotation-actions { display:flex; gap:14px; }
.annotation-actions button,.annotation-replies > button,.composer-label button { border:0; background:none; padding:4px 0; font-size:12px; color:var(--ej-muted); }
.annotation-actions button:hover { color:var(--ej-ink); text-decoration:underline; }
.annotation-replies { margin-top:12px; padding-top:10px; border-top:1px solid var(--ej-line); }
.annotation-reply { padding:8px 0; font-size:12px; }
.annotation-reply a { font-weight:650; }
.annotation-reply p { margin:4px 0; }
.annotation-composer { flex-shrink:0; padding:16px; border-top:1px solid var(--ej-line); max-height:55%; overflow:auto; }
.composer-label { display:flex; align-items:center; justify-content:space-between; font-size:13px; }
.annotation-panel textarea { display:block; box-sizing:border-box; width:100%; padding:12px; background:var(--ej-bg,#f2efe6); color:var(--ej-ink); border:1px solid var(--ej-line); border-radius:12px; font:inherit; line-height:1.6; resize:vertical; min-height:70px; max-height:180px; }
.annotation-panel textarea:focus { outline:2px solid var(--ej-ink); outline-offset:2px; }
.annotation-submit-row { display:flex; justify-content:space-between; align-items:center; margin-top:12px; gap:8px; }
.annotation-submit-row small { color:var(--ej-muted); }
.annotation-panel .annotation-primary,.annotation-primary { background:var(--ej-ink,#171715); color:var(--ej-surface,#fffdf7); border:1px solid var(--ej-ink); padding:8px 16px; border-radius:99px; }
.annotation-footer { padding:16px 20px; border-top:1px solid var(--ej-line); font-size:12px; color:var(--ej-muted); }
.annotation-empty { display:flex; flex-direction:column; align-items:center; padding:40px 8px; text-align:center; color:var(--ej-muted); line-height:1.8; }
.annotation-empty strong { color:var(--ej-ink); font-size:16px; }
.annotation-empty p { max-width:250px; margin-top:6px; }
.empty-quote { font-size:58px; line-height:1; color:var(--ej-ink); }
.annotation-notice,.annotation-error { padding:10px 12px; background:#fff0c4; border-radius:8px; font-size:12px; line-height:1.7; }
.annotation-error { background:#fff0e9; }
.annotation-load-more { width:100%; border:1px solid var(--ej-line); border-radius:99px; padding:10px; background:transparent; }
.quote-selection-action { position:fixed; z-index:2300; display:flex; align-items:center; gap:6px; padding:9px 14px; border:1px solid var(--ej-ink); border-radius:99px; background:var(--studio-lime,#baff32); color:var(--ej-ink); box-shadow:3px 3px 0 #0002; font-size:12px; white-space:nowrap; }
.quote-selection-action span { font-size:16px; line-height:1; }
.annotation-backdrop { position:fixed; inset:0; background:#0005; z-index:2199; }
.annotation-highlight-fallback span { position:fixed; background:#ffc94d55; pointer-events:none; z-index:1; }
.annotation-dialog-button { padding:8px 16px; margin-left:8px; border:1px solid var(--ej-line); border-radius:99px; background:var(--ej-surface); }
.annotation-dialog-button.annotation-primary { background:var(--ej-ink); }
@media(max-width:760px) { .annotation-panel { right:12px; bottom:12px; width:calc(100vw - 24px); border-radius:18px; } .annotation-header { padding:16px; } .annotation-content { padding:12px; } .annotation-author time { max-width:98px; line-height:1.4; text-align:right; } }
</style>
