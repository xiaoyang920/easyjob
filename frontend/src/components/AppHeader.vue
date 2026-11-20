<template>
  <header class="navbar app-header" aria-label="站点导航">
    <svg v-if="lens" class="header-glass-filter" width="0" height="0" aria-hidden="true" focusable="false">
      <defs>
        <!-- 只负责位移。模糊、遮罩都交给 CSS：同样的效果写成一条 SVG 滤镜时，滚动每帧要多花几毫秒 -->
        <filter id="ej-header-lens" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
          <feImage :href="lens.map" preserveAspectRatio="none" result="map" />
          <feDisplacementMap in="SourceGraphic" in2="map" :scale="lens.scale" xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </defs>
    </svg>
    <!-- 液态玻璃：中部磨砂托住导航文字，外缘一圈按透镜折射背后的内容，最上面是镜面高光 -->
    <div ref="glassSurface" class="header-glass" :class="{ 'has-lens': lens }" :style="lensStyle" aria-hidden="true">
      <span class="header-glass-frost"></span>
      <span class="header-glass-rim"></span>
    </div>
    <HomeBrand />
    <span v-if="title" class="page-title app-header-title">{{ title }}</span>
    <button v-if="searchable" class="header-search-toggle" aria-label="搜索文章" :aria-expanded="mobileSearch" @click="mobileSearch = !mobileSearch"><Search /></button>
    <SearchBox v-if="searchable" v-model="keyword" :class="{ 'mobile-search-open':mobileSearch }" @search="search" />
    <div class="app-header-right">
      <div class="app-header-tools" :class="{ open: toolsOpen }">
        <button v-if="hasActions" class="header-tools-toggle" :aria-expanded="toolsOpen" aria-controls="page-header-actions" @click="toolsOpen = !toolsOpen">页面操作</button>
        <div id="page-header-actions" ref="actions" class="page-header-actions"></div>
      </div>
      <ThemeModeControl />
      <AppNavigation />
    </div>
  </header>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import HomeBrand from './HomeBrand.vue'
import SearchBox from './SearchBox.vue'
import AppNavigation from './AppNavigation.vue'
import ThemeModeControl from './ThemeModeControl.vue'
import { Search } from '@element-plus/icons-vue'
const route = useRoute(), router = useRouter()
const keyword = ref(''), toolsOpen = ref(false), actions = ref<HTMLElement>(), hasActions = ref(false)
const mobileSearch = ref(false)
const glassSurface = ref<HTMLElement>()
type Lens = { map: string; scale: number; rimMask: string; coreMask: string }
const lens = shallowRef<Lens>()
const lensStyle = computed(() => lens.value ? { '--glass-rim-mask': `url("${lens.value.rimMask}")`, '--glass-core-mask': `url("${lens.value.coreMask}")` } : undefined)
// backdrop-filter 里的 SVG 滤镜只有 Chromium 内核会绘制；其他内核即使能解析 url()，也可能丢掉整条背景滤镜，
// 连磨砂一起失效，所以不能只靠 CSS.supports 判断。不满足时保留纯 CSS 磨砂。
const supportsLens = navigator.vendor === 'Google Inc.' && CSS.supports('backdrop-filter', 'url(#ej-header-lens)')

/**
 * 按胶囊形状算出每个像素离外缘的距离 inset，生成三张图：
 * - 位移贴图：R/G 是水平、竖直位移，0.5 表示不偏移。斜面内朝中心采样，越靠外缘位移越大，背景被放大拉伸，像透过玻璃的厚边。
 * - 外缘遮罩 / 中部遮罩：透明度互补，外缘一圈显示透镜层，向内渐变为磨砂层。
 */
function updateLens(width: number, height: number) {
  const columns = Math.round(width), rows = Math.round(height)
  if (!columns || !rows) return
  const canvas = document.createElement('canvas')
  canvas.width = columns
  canvas.height = rows
  const context = canvas.getContext('2d')
  if (!context) return
  const radius = height / 2
  const straight = width / 2 - radius
  const bezel = height * .27
  // 位移随离外缘的距离按平方衰减，最陡处每像素变化 0.85 个像素（小于 1），采样位置单调，背景不会镜像折返
  const maxShift = bezel * .85 / 2
  const scale = Math.ceil(maxShift * 2) + 2
  // 导航图标和文字离外缘至少 12px，那里已经基本是磨砂，文字下面不会透出清晰的背景
  const rimStart = height * .05, rimEnd = height * .24
  const map = context.createImageData(columns, rows)
  const rimMask = context.createImageData(columns, rows)
  const coreMask = context.createImageData(columns, rows)
  for (let y = 0; y < rows; y++) {
    const dy = (y + .5) * height / rows - radius
    for (let x = 0; x < columns; x++) {
      const dx = (x + .5) * width / columns - width / 2
      const capX = Math.max(Math.abs(dx) - straight, 0)
      const distance = Math.hypot(capX, dy)
      const inset = radius - distance
      const depth = Math.min(Math.max(1 - inset / bezel, 0), 1)
      const shift = maxShift * depth * depth
      const unitX = distance ? Math.sign(dx) * capX / distance : 0
      const unitY = distance ? dy / distance : 0
      const fade = Math.min(Math.max((inset - rimStart) / (rimEnd - rimStart), 0), 1)
      const rimWeight = 255 * (1 - fade * fade * (3 - 2 * fade))
      const offset = (y * columns + x) * 4
      map.data[offset] = 255 * (.5 - unitX * shift / scale)
      map.data[offset + 1] = 255 * (.5 - unitY * shift / scale)
      map.data[offset + 3] = 255
      rimMask.data[offset + 3] = rimWeight
      coreMask.data[offset + 3] = 255 - rimWeight
    }
  }
  const encode = (image: ImageData) => { context.putImageData(image, 0, 0); return canvas.toDataURL() }
  lens.value = { map: encode(map), scale, rimMask: encode(rimMask), coreMask: encode(coreMask) }
}
const titles: Record<string,string> = { AiChat:'智能助手', Chat:'私信', Notifications:'消息通知', DraftBox:'草稿与审核', CreateArticle:'写文章', EditArticle:'编辑文章', EditProfile:'编辑资料', SpaceCustomization:'空间装扮', FollowersFollowing:'粉丝与关注', MemoryManagement:'长期记忆', AccountSecurity:'账号安全', PasswordReset:'找回密码', AdminConsole:'管理后台', ArticleDetail:'文章' }
const title = computed(() => route.name === 'GrowthShop' ? '硬币商城' : titles[String(route.name)] || '')
const searchable = computed(() => ['Home','Search','UserSpace'].includes(String(route.name)))
function search(value: string) { void router.push({ path:'/search', query:{ keyword:value } }) }
watch(() => route.fullPath, () => { keyword.value = String(route.query.keyword || ''); toolsOpen.value = false; mobileSearch.value = false }, { immediate:true })
function outside(event: PointerEvent) { if (!(event.target as HTMLElement).closest('.app-header-tools')) toolsOpen.value = false }
let observer: MutationObserver | undefined
let glassObserver: ResizeObserver | undefined
onMounted(() => {
  observer = new MutationObserver(() => { hasActions.value = !!actions.value?.children.length })
  if (actions.value) { observer.observe(actions.value, {childList:true}); hasActions.value = !!actions.value.children.length }
  if (glassSurface.value && supportsLens) {
    glassObserver = new ResizeObserver(([entry]) => {
      const box = entry.borderBoxSize[0]
      updateLens(box.inlineSize, box.blockSize)
    })
    glassObserver.observe(glassSurface.value)
  }
  document.addEventListener('pointerdown', outside)
})
onUnmounted(() => { observer?.disconnect(); glassObserver?.disconnect(); document.removeEventListener('pointerdown', outside) })
</script>
<style>
#app .navbar.app-header {
  position: fixed;
  inset: 0 0 auto;
  z-index: var(--ej-layer-header);
  display: flex;
  align-items: center;
  gap: 18px;
  height: var(--ej-header-height);
  background: transparent;
  box-shadow: none;
  -webkit-backdrop-filter: none;
  backdrop-filter: none;
}
#app .header-glass-filter { position: absolute; pointer-events: none; }
/* 玻璃感来自：几乎透明的染色、背景折射与磨砂、1px 镜面高光和柔和投影。
   不用大面积的内阴影做上亮下暗的“鼓包”，那种明暗会让表面看起来像塑料。
   叠放顺序：磨砂层、透镜层（各自读取背后的页面），再往上是不参与滤镜的斜面受光和镜面高光。 */
#app .header-glass {
  position: absolute;
  z-index: -1;
  inset: 5px clamp(6px, 1.4vw, 28px);
  border-radius: 999px;
  pointer-events: none;
  box-shadow:
    0 0 0 .5px rgb(17 17 15 / .12),
    0 1px 2px rgb(48 37 27 / .06),
    0 14px 32px -16px rgb(48 37 27 / .32);
}
#app :is(.header-glass-frost, .header-glass-rim),
#app .header-glass::before,
#app .header-glass::after { position: absolute; inset: 0; border-radius: inherit; pointer-events: none; }
/* 磨砂层的染色决定文字可读性：背后是深色封面时，墨色文字仍要看得清；外缘的透镜层染色更淡，保留背景的颜色。
   两层的饱和度都只略微提高：背后的图片更鲜亮，纸色本身不会被推成黄色。 */
#app .header-glass-frost {
  background: linear-gradient(180deg, rgb(255 253 247 / .3), rgb(255 253 247 / .4) 30% 70%, rgb(255 253 247 / .3));
  -webkit-backdrop-filter: blur(6px) saturate(1.3) brightness(1.04);
  backdrop-filter: blur(6px) saturate(1.3) brightness(1.04);
}
#app .header-glass-rim { display: none; }
/* 两层的遮罩透明度互补（见 updateLens）：外缘显示透镜层，向内渐变为磨砂层 */
#app .has-lens .header-glass-frost {
  backdrop-filter: url(#ej-header-lens) blur(6px) saturate(1.3) brightness(1.04);
  -webkit-mask: var(--glass-core-mask) 0 0 / 100% 100% no-repeat;
  mask: var(--glass-core-mask) 0 0 / 100% 100% no-repeat;
}
/* 透镜层只做极轻的柔化：边缘放大出来的是平滑的拉伸，不会把纸面颗粒拉成一圈刻痕 */
#app .has-lens .header-glass-rim {
  display: block;
  background: rgb(255 253 247 / .1);
  backdrop-filter: url(#ej-header-lens) blur(1.2px) saturate(1.3) brightness(1.04);
  -webkit-mask: var(--glass-rim-mask) 0 0 / 100% 100% no-repeat;
  mask: var(--glass-rim-mask) 0 0 / 100% 100% no-repeat;
}
/* 高光两层画在滤镜层之上，不会被磨砂或折射 */
#app .header-glass::before,
#app .header-glass::after { content: ''; z-index: 1; }
/* 斜面受光：贴着内缘的一道细亮边，左上强、右下弱，显出玻璃的厚度；最外一圈很淡的暗线把镜面高光衬出来 */
#app .header-glass::before {
  box-shadow:
    inset 0 0 0 1.5px rgb(17 17 15 / .045),
    inset 1px 2px 3px -2px rgb(255 255 255 / .95),
    inset -1px -2px 3px -2px rgb(255 255 255 / .55);
}
/* 镜面高光：光从左上方来。左端上沿最亮并沿上边缘渐弱，右端下沿有一道较弱的内部反光 */
#app .header-glass::after {
  padding: 1px;
  background:
    radial-gradient(220px 70px at 44px 0, rgb(255 255 255 / 1), rgb(255 255 255 / 0) 72%),
    radial-gradient(260px 70px at calc(100% - 48px) 100%, rgb(255 255 255 / .85), rgb(255 255 255 / 0) 72%),
    linear-gradient(180deg, rgb(255 255 255 / .85), rgb(255 255 255 / .1) 40%, rgb(255 255 255 / 0) 60%, rgb(255 255 255 / .3));
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0);
}
@media (prefers-reduced-transparency: reduce) {
  #app :is(.header-glass, .has-lens) .header-glass-frost {
    background: var(--ej-surface);
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
    -webkit-mask: none;
    mask: none;
  }
  #app :is(.header-glass, .has-lens) .header-glass-rim { display: none; }
}
/* 页头里的描边按钮带一层浅色底，压在深色内容上时文字依然清楚；悬停仍用主题的青柠色 */
#app .app-header .nav-btn:not(.primary):not(:hover) { background: rgb(255 253 247 / .6); }
#app .app-header > .search-box { width:clamp(180px,28vw,440px); margin-inline:auto; }
#app .app-header-right { margin-left:auto; display:flex; align-items:center; gap:20px; }
#app .page-header-actions, #app .page-header-actions > .nav-right { display:flex; align-items:center; gap:8px; }
#app .page-header-actions:empty { display:none; }
#app .page-header-actions .nav-btn { padding:8px 16px; font:inherit; font-size:13px; cursor:pointer; }
#app .header-tools-toggle { display:none; }
#app .header-search-toggle { display:none; }
/* 页面名称比全站的 muted 灰更深一些：玻璃背后滚过深色封面时也能看清 */
#app .navbar.app-header .app-header-title { margin-left:0; color:var(--ej-ink); border-left-color:var(--ej-line); }
#app .account-security-page, #app .password-reset-page, #app .admin-console, #app .memory-page { padding-top:var(--ej-header-height); }
@media(max-width:900px) {
  #app .navbar.app-header { gap:10px; }
  /* 窄屏的导航按钮已显示当前页面名称，这里隐藏重复的标题。选择器要比 theme.css 里统一页面标题的规则更具体 */
  #app .navbar.app-header .app-header-title { display:none; }
  #app .app-header-right { gap:10px; }
  #app .app-header-tools { position:relative; }
  #app .header-tools-toggle { display:block; font:inherit; font-size:12px; padding:8px 10px; border:1px solid var(--ej-line); border-radius:99px; background:var(--ej-surface); cursor:pointer; }
  #app .page-header-actions { display:none; position:absolute; top:calc(100% + 12px); right:0; padding:12px; border:1px solid var(--ej-ink); border-radius:14px; background:var(--ej-surface); box-shadow:var(--ej-shadow); white-space:nowrap; }
  #app .app-header-tools.open .page-header-actions { display:flex; }
}
@media(max-width:768px) {
  #app .navbar.app-header { padding-inline:18px; }
  #app .app-header > .search-box { width:auto; flex:1; }
  #app .account-security-page, #app .password-reset-page, #app .admin-console, #app .memory-page { padding-top:var(--ej-header-height); }
}
@media(max-width:600px) {
  #app .app-header > .search-box { display:none; }
  #app .header-search-toggle { display:grid; place-items:center; margin-left:auto; padding:8px; border:1px solid var(--ej-line); border-radius:50%; background:var(--ej-surface); }
  #app .header-search-toggle svg { width:18px; height:18px; }
  #app .app-header > .search-box.mobile-search-open { display:block; position:absolute; top:calc(100% + 8px); left:18px; right:18px; width:auto; background:var(--ej-surface); }
  #app .app-header .mobile-search-open .search-history-panel { position:absolute; inset:calc(100% + 8px) 0 auto; }
  #app .app-header-tools .header-tools-toggle { padding:8px; font-size:11px; }
}
</style>
