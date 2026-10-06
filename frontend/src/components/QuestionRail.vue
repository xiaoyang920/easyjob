<template>
  <nav v-if="questions.length >= MIN_QUESTIONS" class="question-rail" aria-label="提问导航">
    <div ref="trackRef" class="rail-track">
      <button
        v-for="(q, order) in questions"
        :key="q.index"
        type="button"
        :class="['rail-tick', { active: q.index === activeIndex }]"
        :aria-label="`跳转到第 ${order + 1} 个提问：${q.question}`"
        :aria-current="q.index === activeIndex ? 'true' : undefined"
        @click="jumpTo(q.index)"
        @mouseenter="showPreview(order, $event)"
        @mouseleave="hidePreview"
        @focus="showPreview(order, $event)"
        @blur="hidePreview"
      >
        <span class="rail-line" aria-hidden="true"></span>
      </button>
    </div>

    <div
      v-if="preview"
      class="rail-preview"
      role="tooltip"
      :style="{ top: `${preview.top}px` }"
    >
      <p class="preview-eyebrow">第 {{ preview.order + 1 }} 问</p>
      <p class="preview-question">{{ preview.question }}</p>
      <p v-if="preview.answer" class="preview-answer">{{ preview.answer }}</p>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'

interface RailMessage {
  role: 'user' | 'assistant'
  content: string
  image?: string | null
}

interface Question {
  index: number
  question: string
  answer: string
}

const props = defineProps<{
  messages: RailMessage[]
  container: HTMLElement
}>()

// 少于两个提问时没有“定位”的意义
const MIN_QUESTIONS = 2
// 跳转后提问气泡与消息区顶部保留的间距
const JUMP_GAP = 16
// 判定线 = 跳转落点 + 容差：提问越过这条线才算“当前”，与点击跳转后的停留位置一致
const ACTIVE_LINE_TOLERANCE = 12
// 滚动停止多久后视为点击触发的平滑滚动已结束
const SCROLL_SETTLE_MS = 150
// 距顶部/底部多少像素内视为已滚到边界
const EDGE_EPSILON = 4
const QUESTION_PREVIEW_LENGTH = 60
const ANSWER_PREVIEW_LENGTH = 90

const trackRef = ref<HTMLElement>()
const activeIndex = ref(-1)
const preview = ref<{ order: number; top: number; question: string; answer: string } | null>(null)
let frame = 0
// 点击跳转引发的滚动期间锁定点击项，避免滚动计算把高亮改成相邻提问
let lockedIndex = -1
let settleTimer: ReturnType<typeof setTimeout> | undefined

// 去掉 Markdown 标记和引用编号，只保留可读的纯文本摘要
function toPlainPreview(text: string, maxLength: number): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\[(\d+|[a-z_]+:\d+)\]/gi, '')
    .replace(/^\s*(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    .replace(/[*_~|]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength)
}

// 每个提问配上它之后、下一个提问之前的第一条回答
const questions = computed<Question[]>(() => {
  const result: Question[] = []
  props.messages.forEach((message, index) => {
    if (message.role !== 'user') return
    const question = toPlainPreview(message.content || '', QUESTION_PREVIEW_LENGTH) || (message.image ? '[图片]' : '（空消息）')
    let answer = ''
    for (let next = index + 1; next < props.messages.length && props.messages[next].role !== 'user'; next++) {
      answer = toPlainPreview(props.messages[next].content || '', ANSWER_PREVIEW_LENGTH)
      if (answer) break
    }
    result.push({ index, question, answer })
  })
  return result
})

function messageElement(index: number): HTMLElement | null {
  return props.container.querySelector<HTMLElement>(`[data-msg-index="${index}"]`)
}

// 消息在滚动容器内容中的纵向位置
function offsetInContainer(element: HTMLElement): number {
  return element.getBoundingClientRect().top - props.container.getBoundingClientRect().top + props.container.scrollTop
}

function updateActive() {
  frame = 0
  const list = questions.value
  if (list.length < MIN_QUESTIONS) return
  const { scrollTop, clientHeight, scrollHeight } = props.container
  // 已滚到顶：无法再往上滚，相邻的短问答都挤在顶部时也应选中第一问
  if (scrollTop < EDGE_EPSILON) {
    activeIndex.value = list[0].index
    return
  }
  // 已滚到底：最后一问即为当前项，即使它离顶部还很远
  if (scrollHeight - scrollTop - clientHeight < EDGE_EPSILON) {
    activeIndex.value = list[list.length - 1].index
    return
  }
  const activeLine = scrollTop + JUMP_GAP + ACTIVE_LINE_TOLERANCE
  let current = list[0].index
  for (const q of list) {
    const element = messageElement(q.index)
    if (element && offsetInContainer(element) <= activeLine) current = q.index
  }
  activeIndex.value = current
}

function handleScroll() {
  // 跳转引发的滚动：保持点击项高亮，等滚动停止后再解除锁定。
  // 解除时不重新计算，之后由用户自己的滚动触发更新。
  if (lockedIndex >= 0) {
    clearTimeout(settleTimer)
    settleTimer = setTimeout(() => { lockedIndex = -1 }, SCROLL_SETTLE_MS)
    activeIndex.value = lockedIndex
    return
  }
  if (!frame) frame = requestAnimationFrame(updateActive)
}

function jumpTo(index: number) {
  const element = messageElement(index)
  if (!element) return
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const target = Math.max(0, offsetInContainer(element) - JUMP_GAP)
  activeIndex.value = index
  // 目标位置与当前位置相同则不会产生滚动事件，无需锁定
  if (Math.abs(target - props.container.scrollTop) < 1) return
  lockedIndex = index
  clearTimeout(settleTimer)
  // 兜底：滚动被浏览器截断（例如已到边界）时也能及时解除锁定
  settleTimer = setTimeout(() => { lockedIndex = -1 }, SCROLL_SETTLE_MS * 4)
  props.container.scrollTo({ top: target, behavior: reduceMotion ? 'auto' : 'smooth' })
}

function showPreview(order: number, event: Event) {
  const tick = event.currentTarget as HTMLElement
  const track = trackRef.value
  if (!track) return
  const q = questions.value[order]
  preview.value = {
    order,
    top: tick.offsetTop - track.scrollTop + tick.offsetHeight / 2,
    question: q.question,
    answer: q.answer,
  }
}

function hidePreview() {
  preview.value = null
}

// 提问很多时刻度条本身会滚动，保持当前刻度可见
function keepActiveTickVisible() {
  const track = trackRef.value
  const tick = track?.querySelector<HTMLElement>('.rail-tick.active')
  if (!track || !tick) return
  if (tick.offsetTop < track.scrollTop || tick.offsetTop + tick.offsetHeight > track.scrollTop + track.clientHeight) {
    track.scrollTo({ top: tick.offsetTop - track.clientHeight / 2 })
  }
}

watch(activeIndex, () => nextTick(keepActiveTickVisible))

// 切换会话时消息区元素会重建，需要重新绑定滚动监听
watch(
  () => props.container,
  (current, previous) => {
    previous?.removeEventListener('scroll', handleScroll)
    current.addEventListener('scroll', handleScroll, { passive: true })
    nextTick(handleScroll)
  },
  { immediate: true },
)

// 新提问、流式回答都会改变内容高度，重新计算当前项
watch(() => props.messages.map(m => m.content.length).join(','), () => nextTick(handleScroll))

onUnmounted(() => {
  props.container.removeEventListener('scroll', handleScroll)
  cancelAnimationFrame(frame)
  clearTimeout(settleTimer)
})
</script>

<style scoped>
.question-rail {
  position: absolute;
  left: 10px;
  top: 50%;
  z-index: 20;
  transform: translateY(-50%);
}

.rail-track {
  display: flex;
  flex-direction: column;
  max-height: min(60vh, 520px);
  overflow-y: auto;
  scrollbar-width: none;
}

.rail-track::-webkit-scrollbar {
  display: none;
}

.rail-tick {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  width: 32px;
  height: 11px;
  padding: 0 4px;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.rail-line {
  display: block;
  width: 10px;
  height: 2px;
  border-radius: 2px;
  background: #11110f33;
  transition: width 220ms var(--studio-spring), background 180ms ease, height 180ms ease;
}

.rail-tick:hover .rail-line,
.rail-tick:focus-visible .rail-line {
  width: 16px;
  background: #11110f80;
}

.rail-tick.active .rail-line {
  width: 22px;
  height: 3px;
  background: var(--ej-ink);
}

.rail-tick:focus-visible {
  outline: 2px solid var(--ej-accent);
  outline-offset: 0;
  border-radius: 4px;
}

.rail-preview {
  position: absolute;
  left: 38px;
  width: 280px;
  padding: 12px 14px;
  background: var(--ej-surface);
  border: 1px solid var(--ej-ink);
  border-radius: 14px;
  box-shadow: var(--ej-shadow);
  transform: translateY(-50%);
  pointer-events: none;
  animation: preview-in 160ms var(--ej-ease);
}

.preview-eyebrow {
  margin: 0 0 4px;
  color: var(--ej-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
}

.preview-question {
  margin: 0;
  overflow: hidden;
  color: var(--ej-ink);
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.preview-answer {
  display: -webkit-box;
  margin: 6px 0 0;
  overflow: hidden;
  color: #47453f;
  font-size: 12px;
  line-height: 1.6;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

@keyframes preview-in {
  from { opacity: 0; transform: translate(-4px, -50%); }
  to { opacity: 1; transform: translate(0, -50%); }
}

/* 消息区内容最宽 780px 居中；视口低于约 1180px 时左侧留白不足 48px，刻度会压住头像，直接隐藏 */
@media (max-width: 1180px) {
  .question-rail { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .rail-line, .rail-preview { transition: none; animation: none; }
}
</style>
