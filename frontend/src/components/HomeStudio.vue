<template>
  <div ref="studio" class="home-studio">
    <div class="studio-grain" aria-hidden="true"></div>
    <div class="studio-progress" aria-hidden="true"><span ref="progress"></span></div>
    <div ref="cursor" class="studio-cursor" aria-hidden="true"><span>{{ cursorLabel }}</span></div>

    <header class="studio-intro">
      <div class="studio-intro-copy">
        <p class="studio-index"><span></span> 技术创作社区 <i>EASYJOB / JOURNAL</i></p>
        <h1>把经验写下来，<br>让好想法<span class="studio-underline">被看见。</span></h1>
        <p class="studio-description">记录一次实践，分享一个发现。<br>在这里，遇见同样好奇的人。</p>
        <div class="studio-actions">
          <button class="studio-write" data-home-magnetic @click="$emit('write')">开始写作 <span aria-hidden="true">↗</span></button>
          <button class="studio-browse" @click="browse">看看大家在写什么 <span aria-hidden="true">↓</span></button>
        </div>
      </div>
      <div class="studio-illustration" role="group" aria-label="记录、探索与共创">
        <span class="studio-orbit" aria-hidden="true"></span>
        <span class="studio-art-note" aria-hidden="true">DIFFERENT MINDS. SHARED IDEAS.</span>
        <div class="studio-stack">
          <span class="studio-spark" aria-hidden="true">✳</span>
          <!-- 01 记录：写作稿 -->
          <button type="button" class="studio-sheet studio-sheet--write" data-home-parallax="16" @click="$emit('write')" aria-label="开始记录，创作文章">
            <svg class="sheet-svg" viewBox="0 0 160 200" aria-hidden="true">
              <rect class="sheet-shadow" x="7" y="8" width="150" height="188" rx="14"/>
              <g class="sheet-paper">
                <rect class="sheet-card" x="2" y="2" width="150" height="188" rx="14"/>
                <path class="sheet-head" d="M2 16a14 14 0 0 1 14-14h122a14 14 0 0 1 14 14v20H2Z"/>
                <path class="sheet-rule" d="M2 36h150"/>
                <rect class="sheet-frame" x="2" y="2" width="150" height="188" rx="14"/>
                <text class="sheet-label" x="14" y="24">01 · 记录</text>
                <circle class="sheet-pin" cx="134" cy="19" r="4"/>
                <rect class="sheet-ink" x="16" y="52" width="98" height="9" rx="4.5"/>
                <rect class="sheet-text" x="16" y="72" width="122" height="5" rx="2.5"/>
                <rect class="sheet-text" x="16" y="84" width="108" height="5" rx="2.5"/>
                <rect class="sheet-mark" x="13" y="93" width="88" height="12" rx="3"/>
                <rect class="sheet-text sheet-text--strong" x="16" y="96.5" width="80" height="5" rx="2.5"/>
                <rect class="sheet-text" x="16" y="110" width="116" height="5" rx="2.5"/>
                <rect class="sheet-text" x="16" y="122" width="70" height="5" rx="2.5"/>
                <rect class="sheet-caret" x="90" y="118" width="2.5" height="13" rx="1"/>
                <rect class="sheet-ink" x="16" y="140" width="122" height="36" rx="7"/>
                <rect class="sheet-code sheet-code--lime" x="24" y="150" width="42" height="4" rx="2"/>
                <rect class="sheet-code sheet-code--muted" x="72" y="150" width="30" height="4" rx="2"/>
                <rect class="sheet-code sheet-code--violet" x="24" y="160" width="74" height="4" rx="2"/>
              </g>
            </svg>
          </button>
          <!-- 02 探索：标签与文章列表 -->
          <button type="button" class="studio-sheet studio-sheet--explore" data-home-parallax="24" @click="browse" aria-label="探索社区文章">
            <svg class="sheet-svg" viewBox="0 0 160 200" aria-hidden="true">
              <rect class="sheet-shadow" x="7" y="8" width="150" height="188" rx="14"/>
              <g class="sheet-paper">
                <rect class="sheet-card" x="2" y="2" width="150" height="188" rx="14"/>
                <path class="sheet-head" d="M2 16a14 14 0 0 1 14-14h122a14 14 0 0 1 14 14v20H2Z"/>
                <path class="sheet-rule" d="M2 36h150"/>
                <rect class="sheet-frame" x="2" y="2" width="150" height="188" rx="14"/>
                <text class="sheet-label" x="14" y="24">02 · 探索</text>
                <rect class="sheet-field" x="14" y="48" width="126" height="22" rx="11"/>
                <rect class="sheet-text" x="24" y="57" width="58" height="4" rx="2"/>
                <circle class="sheet-stroke" cx="125" cy="58" r="4.5"/>
                <path class="sheet-stroke" d="M128.5 61.5 132 65"/>
                <!-- 两侧标签会被相邻卡片遮挡，只保留色块，避免露出半截文字 -->
                <rect class="sheet-chip sheet-chip--violet" x="14" y="80" width="46" height="18" rx="9"/>
                <rect class="sheet-chip sheet-chip--coral" x="64" y="80" width="38" height="18" rx="9"/>
                <text class="sheet-chip-text" x="71" y="92.5">#RAG</text>
                <rect class="sheet-chip sheet-chip--lime" x="106" y="80" width="34" height="18" rx="9"/>
                <rect class="sheet-thumb sheet-thumb--coral" x="14" y="110" width="24" height="24" rx="6"/>
                <rect class="sheet-ink" x="46" y="113" width="92" height="5" rx="2.5"/>
                <rect class="sheet-text" x="46" y="124" width="62" height="4" rx="2"/>
                <rect class="sheet-thumb sheet-thumb--lime" x="14" y="144" width="24" height="24" rx="6"/>
                <rect class="sheet-ink" x="46" y="147" width="84" height="5" rx="2.5"/>
                <rect class="sheet-text" x="46" y="158" width="54" height="4" rx="2"/>
                <text class="sheet-more" x="14" y="183">MORE ↓</text>
              </g>
            </svg>
          </button>
          <!-- 03 共创：AI 对话 -->
          <button type="button" class="studio-sheet studio-sheet--create" data-home-parallax="20" @click="$emit('assistant')" aria-label="与写作助手共创">
            <svg class="sheet-svg" viewBox="0 0 150 184" aria-hidden="true">
              <rect class="sheet-shadow" x="7" y="8" width="140" height="172" rx="14"/>
              <g class="sheet-paper">
                <rect class="sheet-card" x="2" y="2" width="140" height="172" rx="14"/>
                <path class="sheet-head" d="M2 16a14 14 0 0 1 14-14h112a14 14 0 0 1 14 14v20H2Z"/>
                <path class="sheet-rule" d="M2 36h140"/>
                <rect class="sheet-frame" x="2" y="2" width="140" height="172" rx="14"/>
                <text class="sheet-label" x="14" y="24">03 · 共创</text>
                <rect class="sheet-ink" x="46" y="48" width="84" height="30" rx="12"/>
                <rect class="sheet-code" x="56" y="57" width="62" height="4" rx="2"/>
                <rect class="sheet-code sheet-code--muted" x="56" y="66" width="40" height="4" rx="2"/>
                <rect class="sheet-bubble" x="14" y="88" width="104" height="44" rx="12"/>
                <text class="sheet-ai-mark" x="22" y="106">✳</text>
                <rect class="sheet-ink" x="38" y="98" width="70" height="4" rx="2"/>
                <rect class="sheet-text sheet-text--strong" x="24" y="110" width="84" height="4" rx="2"/>
                <rect class="sheet-text sheet-text--strong" x="24" y="119" width="58" height="4" rx="2"/>
                <rect class="sheet-field" x="14" y="142" width="116" height="20" rx="10"/>
                <rect class="sheet-text" x="24" y="150" width="46" height="4" rx="2"/>
                <circle class="sheet-send" cx="120" cy="152" r="6.5"/>
                <path class="sheet-stroke sheet-stroke--thin" d="M117.5 152h5m-2-2.2 2.2 2.2-2.2 2.2"/>
              </g>
            </svg>
          </button>
        </div>
      </div>
    </header>
    <div class="studio-rule" aria-hidden="true"><span>READ / WRITE / CONNECT</span><span>让每一次分享，都有回响。 <i>✳</i></span></div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import '@/styles/home-studio.css'
import { updateCardTilt } from '@/utils/cardMotion'

defineEmits<{ write: []; assistant: [] }>()
const studio = ref<HTMLElement>()
const cursor = ref<HTMLElement>()
const progress = ref<HTMLElement>()
const cursorLabel = ref('')
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)')
let root: HTMLElement | null = null
let revealObserver: IntersectionObserver | undefined
let mutationObserver: MutationObserver | undefined
let frame = 0
let pointerFrame = 0
let pointerX = 0
let pointerY = 0
let ringX = 0
let ringY = 0
let tilted: HTMLElement | null = null
let magnetic: HTMLElement | null = null
const seen = new WeakSet<Element>()

function browse() {
  const target = root?.querySelector('.category-nav') || root?.querySelector('.articles-section')
  target?.scrollIntoView({ behavior: reduced.matches ? 'instant' : 'smooth', block: 'start' })
}
function registerReveals() {
  root?.querySelectorAll('.article-card, .feature-card').forEach(element => {
    if (seen.has(element)) return
    seen.add(element)
    element.classList.add('studio-reveal')
    if (reduced.matches) element.classList.add('is-visible')
    else revealObserver?.observe(element)
  })
}
function updateScroll() {
  frame = 0
  const maximum = Math.max(document.documentElement.scrollHeight - innerHeight, 1)
  if (progress.value) progress.value.style.transform = `scaleX(${Math.min(1, scrollY / maximum)})`
  root?.classList.toggle('studio-scrolled', scrollY > 24)
}
function scheduleScroll() { if (!frame) frame = requestAnimationFrame(updateScroll) }
function renderPointer() {
  ringX += (pointerX - ringX) * .22
  ringY += (pointerY - ringY) * .22
  if (cursor.value) cursor.value.style.transform = `translate3d(${ringX}px, ${ringY}px, 0)`
  pointerFrame = Math.abs(pointerX - ringX) + Math.abs(pointerY - ringY) > .3 ? requestAnimationFrame(renderPointer) : 0
}
function resetTilt() {
  if (tilted) { tilted.style.removeProperty('--tilt-x'); tilted.style.removeProperty('--tilt-y'); tilted = null }
}
function movePointer(event: PointerEvent) {
  if (event.pointerType !== 'mouse' || reduced.matches || !finePointer.matches) return
  if (!root?.classList.contains('studio-pointer')) { ringX = event.clientX; ringY = event.clientY }
  root?.classList.add('studio-pointer')
  pointerX = event.clientX
  pointerY = event.clientY
  if (!pointerFrame) pointerFrame = requestAnimationFrame(renderPointer)
  const target = event.target instanceof Element ? event.target : null
  const interactive = target?.closest('a, button:not(:disabled), [role="link"], .feature-card')
  const textInput = target?.closest('input, textarea, [contenteditable="true"]')
  cursor.value?.classList.toggle('is-active', !!interactive)
  cursor.value?.classList.toggle('is-input', !!textInput)
  cursorLabel.value = interactive?.matches('.article-card') ? '阅读' : interactive?.matches('.studio-sheet') ? '打开' : ''
  const card = target?.closest<HTMLElement>('.article-card') || null
  if (card !== tilted) resetTilt()
  if (card) {
    tilted = card
    updateCardTilt(card, event)
  }
  const button = target?.closest<HTMLElement>('[data-home-magnetic]') || null
  if (button !== magnetic) magnetic?.style.removeProperty('translate')
  magnetic = button
  if (button) {
    const bounds = button.getBoundingClientRect()
    button.style.translate = `${(event.clientX - bounds.left - bounds.width / 2) * .1}px ${(event.clientY - bounds.top - bounds.height / 2) * .1}px`
  }
  root?.querySelectorAll<HTMLElement>('[data-home-parallax]').forEach(sheet => {
    const depth = Number(sheet.dataset.homeParallax)
    sheet.style.setProperty('--parallax-x', `${(event.clientX / innerWidth - .5) * depth}px`)
    sheet.style.setProperty('--parallax-y', `${(event.clientY / innerHeight - .5) * depth}px`)
  })
}
function leavePointer() {
  root?.classList.remove('studio-pointer')
  cancelAnimationFrame(pointerFrame)
  pointerFrame = 0
  resetTilt()
  magnetic?.style.removeProperty('translate')
  magnetic = null
  root?.querySelectorAll<HTMLElement>('[data-home-parallax]').forEach(sheet => {
    sheet.style.removeProperty('--parallax-x'); sheet.style.removeProperty('--parallax-y')
  })
}
function changePreferences() {
  leavePointer()
  if (reduced.matches) root?.querySelectorAll('.studio-reveal').forEach(element => element.classList.add('is-visible'))
}
onMounted(() => {
  root = studio.value?.closest<HTMLElement>('.home-page') || null
  revealObserver = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add('is-visible'); revealObserver?.unobserve(entry.target) }
  }), { threshold: .06 })
  registerReveals()
  mutationObserver = new MutationObserver(registerReveals)
  if (root) mutationObserver.observe(root, { childList: true, subtree: true })
  root?.addEventListener('pointermove', movePointer, { passive: true })
  root?.addEventListener('pointerleave', leavePointer)
  window.addEventListener('scroll', scheduleScroll, { passive: true })
  window.addEventListener('resize', scheduleScroll, { passive: true })
  reduced.addEventListener('change', changePreferences)
  finePointer.addEventListener('change', changePreferences)
  updateScroll()
})
onUnmounted(() => {
  leavePointer()
  cancelAnimationFrame(frame)
  revealObserver?.disconnect()
  mutationObserver?.disconnect()
  root?.removeEventListener('pointermove', movePointer)
  root?.removeEventListener('pointerleave', leavePointer)
  window.removeEventListener('scroll', scheduleScroll)
  window.removeEventListener('resize', scheduleScroll)
  reduced.removeEventListener('change', changePreferences)
  finePointer.removeEventListener('change', changePreferences)
})
</script>
