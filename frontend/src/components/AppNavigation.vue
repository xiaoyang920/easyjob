<template>
  <div ref="root" class="app-navigation" @keydown.esc="closeMenus">
    <template v-if="signedIn">
      <div class="app-nav-account" :class="{ 'is-open': accountOpen }" @pointerenter="enterAccount" @pointerleave="leaveAccount" @focusout="leaveAccountFocus">
        <button class="app-nav-avatar" :aria-expanded="accountOpen" aria-controls="app-account-panel" aria-label="账户菜单" @pointerdown="beginAvatarPress" @click="toggleAccount" @keydown.down.prevent="openAccount">
          <span class="app-nav-avatar-visual">
          <img v-if="avatarUrl" :src="avatarUrl" alt="用户头像" @error="avatarUrl = ''"><img v-else :src="avatarPlaceholder(displayName)" alt="用户头像">
          </span>
        </button>
        <Transition name="app-account" :duration="220">
          <div v-if="accountOpen" id="app-account-panel" class="app-account-menu">
            <div class="app-account-card">
            <div class="app-account-identity">
              <RouterLink to="/user-space" class="app-account-name" :aria-label="`${displayName}的个人空间`" title="查看个人空间">{{ displayName }}</RouterLink>
              <span v-if="readingLevel !== undefined" class="app-account-level" :aria-label="`阅读等级 L${readingLevel}`" title="累计有效阅读获得的等级">L{{ readingLevel }}</span>
            </div>
            <div class="app-account-stats" aria-label="用户统计">
              <RouterLink :to="followingPath"><strong>{{ accountStats?.followingCount ?? '—' }}</strong><span>关注</span></RouterLink>
              <RouterLink :to="followersPath"><strong>{{ accountStats?.followerCount ?? '—' }}</strong><span>粉丝</span></RouterLink>
              <RouterLink to="/user-space"><strong>{{ accountStats?.articleCount ?? '—' }}</strong><span>文章</span></RouterLink>
            </div>
            <nav class="app-account-items" aria-label="账户设置">
              <RouterLink to="/edit-profile"><EditPen />编辑资料</RouterLink>
              <RouterLink to="/account-security"><Lock />账号安全</RouterLink>
              <RouterLink v-if="administrator" to="/admin" class="app-account-admin"><Monitor />管理后台</RouterLink>
            </nav>
            <button class="app-account-logout" @click="signOut"><SwitchButton />退出登录</button>
            </div>
          </div>
        </Transition>
      </div>
      <button class="app-nav-toggle" :aria-expanded="mobileOpen" aria-controls="app-navigation-links" @click="mobileOpen = !mobileOpen; accountOpen = false">
        <component :is="mobileOpen ? Close : Menu" /><span>{{ currentLabel }}</span>
      </button>
      <nav id="app-navigation-links" class="app-nav-links" :class="{ 'is-open': mobileOpen }" aria-label="平台导航">
        <RouterLink v-for="item in links" :key="item.path" :to="item.path" class="app-nav-link" :class="{ 'is-current': currentPath === item.path }" :aria-current="currentPath === item.path ? 'page' : undefined">
          <span class="app-nav-icon"><component :is="item.icon" /><span v-if="badge(item.path)" class="app-nav-badge">{{ badge(item.path) > 99 ? '99+' : badge(item.path) }}</span></span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
    </template>
    <template v-else>
      <button class="nav-btn" @click="login">登录</button>
      <button class="nav-btn primary" @click="register">注册</button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { signOutSession } from '@/utils/authSession'
import { aiRunCount } from '@/utils/aiRuns'
import { ElMessage } from 'element-plus'
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { EditPen, Document, ChatDotRound, Bell, User, Menu, Close, SwitchButton, Lock, Monitor } from '@element-plus/icons-vue'
import request from '@/utils/request'
import { avatarPlaceholder } from '@/utils/avatar'
import { eventBus, EVENT_AUTH_CHANGED } from '@/utils/eventBus'
import { notifyUnreadCount, fetchNotifyUnreadCount, connectNotifyStream, closeNotifyStream, resetNotifyState } from '@/utils/notification'

type AccountStats = { followingCount: number; followerCount: number; articleCount: number }
const props = withDefaults(defineProps<{ authenticated?: boolean; unreadMessages?: number; avatar?: string; nickname?: string; stats?: AccountStats }>(), { authenticated: undefined })
const emit = defineEmits<{ login: []; register: []; logout: [] }>()
const route = useRoute()
const router = useRouter()
const root = ref<HTMLElement>()
const storedSignedIn = ref(!!localStorage.getItem('token'))
const signedIn = computed(() => props.authenticated ?? storedSignedIn.value)
const mobileOpen = ref(false)
const accountOpen = ref(false)
const unread = ref(0)
const avatarUrl = ref('')
const displayName = ref('用户')
const fetchedStats = ref<AccountStats>()
const readingLevel = ref<number>()
const administrator = ref(false)
const accountStats = computed(() => props.stats ?? fetchedStats.value)
const accountUserId = ref(localStorage.getItem('userId') || '')
const followingPath = computed(() => ({ path: '/followers-following', query: { userId: accountUserId.value, tab: 'following' } }))
const followersPath = computed(() => ({ path: '/followers-following', query: { userId: accountUserId.value, tab: 'followers' } }))
let accountCloseTimer: ReturnType<typeof setTimeout> | undefined
let pointerInAccount = false
let statsLoading = false
function cancelAccountClose() { clearTimeout(accountCloseTimer); accountCloseTimer = undefined }
async function loadAccountStats() {
  if (statsLoading || !accountUserId.value || !signedIn.value) return
  const token = localStorage.getItem('token')
  const userId = accountUserId.value
  statsLoading = true
  try {
    const result: any = await request.get(`/user/space/${userId}`)
    if (localStorage.getItem('token') !== token || accountUserId.value !== userId) return
    fetchedStats.value = { followingCount: Number(result.data.followingCount) || 0, followerCount: Number(result.data.followerCount) || 0, articleCount: Number(result.data.articleCount) || 0 }
    const level = result.data.readingProgress?.level
    if (Number.isInteger(level) && level >= 0) readingLevel.value = level
    administrator.value = [2,3,4].includes(result.data.role) && result.data.status === 1
  } catch { /* 保留占位，下一次展开时可重试。 */ }
  finally { statsLoading = false }
}
function openAccount() {
  cancelAccountClose()
  if (accountOpen.value) return
  accountOpen.value = true; mobileOpen.value = false; loadAccountStats()
}
function enterAccount(event: PointerEvent) { if (event.pointerType === 'mouse' && window.matchMedia('(hover: hover)').matches) { pointerInAccount = true; openAccount() } }
function leaveAccount(event: PointerEvent) {
  if (event.pointerType !== 'mouse') return
  pointerInAccount = false; cancelAccountClose(); accountCloseTimer = setTimeout(() => { if (!root.value?.querySelector('.app-nav-account')?.matches(':hover')) accountOpen.value = false }, 240)
}
function toggleAccount(event: MouseEvent) {
  if (pressedPointer === 'touch') {
    if (pressedOpen) closeMenus(); else openAccount()
    pressedPointer = ''
    return
  }
  // 鼠标进入时已经展开，点击不应立刻把悬停面板关掉。
  if (event.detail > 0 && pointerInAccount && window.matchMedia('(hover: hover)').matches) { openAccount(); return }
  if (accountOpen.value) closeMenus(); else openAccount()
}
let pressedPointer = '', pressedOpen = false
function beginAvatarPress(event: PointerEvent) {
  pressedPointer = event.pointerType; pressedOpen = accountOpen.value
  if (event.pointerType === 'touch') { pointerInAccount = false; event.preventDefault() }
}
function leaveAccountFocus(event: FocusEvent) {
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null) && !pointerInAccount) { cancelAccountClose(); accountOpen.value = false }
}
const links = [
  { path: '/create-article', label: '写文章', icon: EditPen },
  { path: '/draft-box', label: '草稿', icon: Document },
  { path: '/chat', label: '消息', icon: ChatDotRound },
  { path: '/notifications', label: '通知', icon: Bell },
  { path: '/user-space', label: '空间', icon: User },
  { path: '/ai-chat', label: 'AI', icon: EditPen },
]
const currentPath = computed(() => route.path.startsWith('/user-space') ? '/user-space' : route.path === '/edit-article' ? '/create-article' : route.path)
const currentLabel = computed(() => links.find(item => item.path === currentPath.value)?.label || '导航')
function badge(path: string) { return path === '/chat' ? (props.unreadMessages ?? unread.value) : path === '/notifications' ? notifyUnreadCount.value : path === '/ai-chat' ? aiRunCount.value : 0 }
function closeMenus() { cancelAccountClose(); mobileOpen.value = false; accountOpen.value = false }
function clickOutside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) closeMenus() }
async function syncAccount() {
  storedSignedIn.value = !!localStorage.getItem('token')
  const uid = localStorage.getItem('userId') || ''
  if (accountUserId.value !== uid || !storedSignedIn.value) {
    fetchedStats.value = undefined
    readingLevel.value = undefined
    administrator.value = false
  }
  accountUserId.value = uid
  displayName.value = props.nickname || localStorage.getItem('nickName') || '用户'
  avatarUrl.value = (props.avatar || localStorage.getItem('avatar') || '').replace(/^https?:\/\/(?:localhost|127\.0\.0\.1):8080/, '')
  if (!signedIn.value) return
  connectNotifyStream()
  await Promise.allSettled([fetchNotifyUnreadCount(), request.get('/chat/total-unread-count').then((res: any) => { unread.value = Number(res.data) || 0 })])
}
function login() { emit('login'); if (props.authenticated === undefined) router.push({path:'/',query:{login:'true',redirect:route.fullPath}}) }
function register() { emit('register'); if (props.authenticated === undefined) router.push({path:'/',query:{register:'true',redirect:route.fullPath}}) }
async function signOut() {
  closeMenus()
  if (route.path !== '/') {
    const failure = await router.push('/')
    if (failure) return
  }
  const revocation = signOutSession()
  storedSignedIn.value = false
  closeNotifyStream()
  resetNotifyState()
  emit('logout')
  eventBus.emit(EVENT_AUTH_CHANGED)
  try { await revocation } catch { ElMessage.warning('本地已退出，服务端注销失败，请联网后再次退出') }
}
// Route changes keep the same navigation instance and notification subscription.
watch(() => route.path, closeMenus)
watch(() => [props.authenticated, props.avatar, props.nickname], syncAccount)
onMounted(() => { syncAccount(); document.addEventListener('pointerdown', clickOutside); eventBus.on(EVENT_AUTH_CHANGED, syncAccount) })
onUnmounted(() => { cancelAccountClose(); document.removeEventListener('pointerdown', clickOutside); eventBus.off(EVENT_AUTH_CHANGED, syncAccount) })
</script>

<style>
#app .app-navigation { position: relative; display: flex; align-items: center; gap: 18px; flex-shrink: 0; }
#app .app-navigation > .nav-btn { min-height: 40px; padding: 9px 18px; font: inherit; font-size: 14px; cursor: pointer; }
#app .app-nav-links { display: flex; align-items: center; gap: 6px; }
#app .app-nav-link { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 48px; padding: 7px 8px; color: var(--ej-ink); text-decoration: none; border: 1px solid transparent; border-radius: 12px; font-size: 11px; line-height: 1.3; transition: background 180ms, transform 250ms var(--studio-spring); }
#app .app-nav-link:hover { background: var(--ej-surface); transform: translateY(-2px); }
#app .app-nav-link.is-current { background: var(--studio-lime); border-color: var(--ej-ink); }
#app .app-nav-icon { position: relative; display: flex; }
#app .app-navigation svg { width: 20px; height: 20px; }
#app .app-nav-badge { position: absolute; top: -5px; left: 12px; min-width: 15px; padding: 1px 3px; border: 1px solid var(--ej-ink); border-radius: 99px; background: var(--studio-coral); font-size: 9px; line-height: 12px; text-align: center; }
#app .app-nav-account { position: relative; }
#app .app-nav-account::before { content: ''; position: absolute; inset: -18px; }
#app .app-nav-avatar { position: relative; z-index: 2; width: 36px; height: 36px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--ej-ink); cursor: pointer; }
/* 按钮及外层命中区域不动，只缩放没有指针事件的头像视觉层。 */
#app .app-nav-avatar-visual { position: absolute; inset: 0; display: grid; place-items: center; border: 1px solid var(--ej-ink); border-radius: 50%; background: var(--ej-surface); overflow: hidden; pointer-events: none; transition: transform 300ms cubic-bezier(.4,0,.2,1), box-shadow 200ms; }
#app .app-nav-account.is-open .app-nav-avatar-visual { transform: scale(2); box-shadow: 0 4px 16px #11110f20; }
#app .app-nav-avatar img { width: 100%; height: 100%; object-fit: cover; }
#app .app-account-menu { position: absolute; z-index: 1; left: calc(50% - 140px); top: 25px; width: min(280px,calc(100vw - 32px)); }
/* 外层保持固定的鼠标命中区域，动画仅发生在内部卡片。桥接间隙，避免移向卡片时触发离开。 */
#app .app-account-menu::before { content: ''; position: absolute; inset: -12px 0 auto; height: 12px; }
#app .app-account-card { padding: 45px 8px 8px; border: 1px solid var(--ej-ink); border-radius: 18px; box-shadow: var(--ej-shadow-lift); background: var(--ej-surface); transform-origin: top center; max-height: calc(100dvh - 110px); overflow-y: auto; }
#app .app-account-identity { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 10px; }
#app .app-account-name { min-width: 0; color: var(--ej-ink); font-size: 17px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#app .app-account-level { flex-shrink: 0; padding: 3px 7px; border: 1px solid var(--ej-ink); border-radius: 99px; background: var(--studio-lime); color: var(--ej-ink); font-size: 11px; font-weight: 700; line-height: 1.2; }
#app .app-account-menu :is(a,button) { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 10px; font: inherit; font-size: 13px; text-decoration: none; color: var(--ej-ink); border: 0; border-radius: 8px; background: transparent; text-align: left; cursor: pointer; }
#app .app-account-menu :is(a,button):hover { background: var(--ej-canvas); }
#app .app-account-identity .app-account-name { display: block; width: auto; padding: 0; border-radius: 0; font-size: 17px; font-weight: 700; line-height: 1.5; text-align: center; }
#app .app-account-identity .app-account-name:hover { background: transparent; text-decoration: underline; text-underline-offset: 4px; }
#app .app-account-stats { display: grid; grid-template-columns: repeat(3,1fr); padding: 8px 0; border-block: 1px solid var(--ej-hairline); }
#app .app-account-stats a { flex-direction: column; gap: 4px; justify-content: center; padding: 8px 4px; }
#app .app-account-stats strong { font-size: 20px; }
#app .app-account-stats span { font-size: 11px; color: var(--ej-muted); }
#app .app-account-items { padding-block: 8px; }
#app .app-account-items .app-account-admin { margin-top: 6px; border-top: 1px solid var(--ej-hairline); border-radius: 0 0 8px 8px; padding-top: 12px; }
#app .app-account-menu .app-account-logout { border-top: 1px solid var(--ej-hairline); border-radius: 0 0 10px 10px; color: #9d4433; }
#app .app-account-enter-active .app-account-card, #app .app-account-leave-active .app-account-card { transition: opacity 180ms, transform 220ms cubic-bezier(.4,0,.2,1); }
#app .app-account-enter-from .app-account-card, #app .app-account-leave-to .app-account-card { opacity: 0; transform: translateY(8px) scale(.98); }
#app .app-account-leave-active { pointer-events: none; }
#app .app-nav-toggle { display: none; }
#app .app-navigation :is(a,button):focus-visible { outline: 2px solid var(--ej-ink); outline-offset: 3px; }
@media(max-width: 1100px) {
  #app .app-navigation { gap: 10px; }
  #app .app-nav-account { position: static; }
  #app .app-nav-account::before { display: none; }
  #app .app-account-menu { left: auto; right: 0; top: calc(100% + 12px); }
  #app .app-account-card { padding-top: 16px; }
  #app .app-nav-account.is-open .app-nav-avatar-visual { transform: scale(1.25); }
  #app .app-nav-toggle { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border: 1px solid var(--ej-ink); border-radius: 99px; background: var(--ej-surface); color: var(--ej-ink); font: inherit; font-size: 12px; cursor: pointer; }
  #app .app-nav-links { display: none; }
  #app .app-nav-links.is-open { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; position: absolute; right: 0; top: calc(100% + 12px); width: min(330px,calc(100vw - 32px)); padding: 12px; border: 1px solid var(--ej-ink); border-radius: 18px; background: var(--ej-surface); box-shadow: var(--ej-shadow-lift); }
  #app .app-nav-link { padding: 12px; font-size: 12px; }
}
@media(prefers-reduced-motion: reduce) {
  #app .app-nav-avatar-visual, #app .app-account-enter-active .app-account-card, #app .app-account-leave-active .app-account-card { transition: none; }
}
</style>
