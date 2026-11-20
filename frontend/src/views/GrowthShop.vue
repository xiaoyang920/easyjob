<template>
  <div class="growth-page"><main class="shop-main">
    <div class="shop-breadcrumb"><RouterLink to="/">社区</RouterLink><span>/</span><span>硬币商城</span></div>
    <div class="shop-heading"><div><h1>硬币商城</h1><p>兑换阅读成长或购买空间装扮。</p></div><button class="shop-button" :disabled="loading" @click="refreshShop"><Refresh />{{ loading ? '刷新中…' : '刷新商城' }}</button></div>
    <div class="shop-summary"><section class="shop-wallet"><span class="wallet-icon"><Coin /></span><div><span>我的硬币</span><strong>{{ balance ?? '—' }}<small>枚</small></strong></div><RouterLink to="/user-space">我的空间 <ArrowRight /></RouterLink></section><ReadingProgress :progress="progress" /></div>
    <p v-if="loadError" role="alert" class="shop-feedback error">{{ loadError }}<button @click="load">重新加载</button></p>
    <p v-if="message" role="status" class="shop-feedback">{{ message }}</p>
    <div class="shop-tabs" role="tablist" aria-label="商城内容">
      <button id="shop-activities-tab" role="tab" :aria-selected="tab === 'activities'" aria-controls="shop-activities" @click="tab = 'activities'">成长套餐</button>
      <button id="shop-skins-tab" role="tab" :aria-selected="tab === 'skins'" aria-controls="shop-skins" @click="tab = 'skins'">空间装扮</button>
      <button id="shop-orders-tab" role="tab" :aria-selected="tab === 'orders'" aria-controls="shop-orders" @click="tab = 'orders'">我的订单<span v-if="unpaidCount">{{ unpaidCount }}</span></button>
    </div>
    <section v-show="tab === 'activities'" id="shop-activities" role="tabpanel" aria-labelledby="shop-activities-tab">
      <div class="shop-section-heading"><h2>把硬币变成阅读成长</h2><span>每人每场限一份</span></div>
      <ContentState v-if="loading && !activities.length" kind="loading" title="正在加载成长套餐" />
      <ContentState v-else-if="!activities.length && !loadError" kind="empty" title="暂时没有开放的套餐" description="新的兑换活动发布后，会出现在这里。" />
      <div class="activity-grid"><article v-for="a in activities" :key="a.activityId" class="shop-product">
        <div class="product-banner"><span class="product-badge">{{ activityStatus(a, now) }}</span><span class="product-art" aria-hidden="true"><Reading /></span><strong>{{ a.growthSeconds / 60 }}<span>分钟</span></strong><p>阅读成长时长</p></div>
        <div class="product-info"><h3>{{ a.title }}</h3><p class="product-description">成长永久累计，计入阅读等级。</p><div class="product-price"><strong><Coin />{{ a.coinPrice }}</strong><span>硬币 / 份</span></div><div class="product-stock"><span>剩余 {{ a.availableStock }} / {{ a.totalStock }} 份</span><small>以兑换结果为准</small></div><p class="product-time">{{ growthTime(a.startsAt) }} — {{ growthTime(a.endsAt) }}</p><button class="shop-button primary" :disabled="disabled(a)" @click="grab(a)">{{ buttonLabel(a) }}</button></div>
      </article></div>
      <aside class="shop-rules"><strong>兑换说明</strong><p>10 硬币可兑换 30 分钟阅读成长，支付成功后自动到账。每人每场限一单，请在订单期限内完成支付；超时名额会归还，本场不能再次参与。</p></aside>
    </section>
    <section v-show="tab === 'skins'" id="shop-skins" role="tabpanel" aria-labelledby="shop-skins-tab">
      <KeepAlive>
        <SpaceSkinShop v-if="tab === 'skins'" ref="skinShop" @balance="balance = $event" @purchase-completed="onDecorationPurchased" />
      </KeepAlive>
    </section>
    <section v-show="tab === 'orders'" id="shop-orders" role="tabpanel" aria-labelledby="shop-orders-tab">
      <div class="shop-section-heading">
        <h2>我的商城订单</h2>
        <span v-if="!loading && !decorationOrdersLoading && !decorationOrderError">共 {{ shopOrders.length }} 单</span>
      </div>
      <p v-if="decorationOrderError" role="alert" class="shop-feedback error">
        {{ decorationOrderError }}<button @click="loadDecorationOrders">重新加载</button>
      </p>
      <ContentState v-if="(loading || decorationOrdersLoading) && !shopOrders.length" kind="loading" title="正在加载订单" />
      <ContentState v-else-if="!shopOrders.length && !pending && !loadError && !decorationOrderError"
        kind="empty" title="还没有商城订单" description="在商城兑换成长套餐或购买空间装扮后，订单会显示在这里。" />
      <article v-for="o in shopOrders" :key="o.kind + ':' + o.orderId" class="shop-order">
        <span class="order-icon" aria-hidden="true"><Reading v-if="o.kind === 'growth'" /><Present v-else /></span>
        <div class="order-content">
          <div class="order-title">
            <h3>{{ o.kind === 'growth' ? `${o.growthSeconds / 60} 分钟阅读成长` : o.title }}</h3>
            <span class="order-state" :class="o.kind === 'growth' ? o.state.toLowerCase() : 'paid'">
              {{ o.kind === 'growth' ? orderStatus(o.state) : '已支付' }}
            </span>
          </div>
          <p>{{ o.coinCost }} 硬币
            <span v-if="o.kind === 'growth' && o.state === 'PENDING'">
              · {{ remaining(o.expiresAt) > 0 ? `请在 ${countdown(o.expiresAt)} 内支付` : '支付已超时，正在关闭订单' }}
            </span>
          </p>
          <small>订单号 {{ o.orderId }}</small>
          <time v-if="o.createdAt" class="order-time" :datetime="o.createdAt">{{ orderDate.format(Date.parse(o.createdAt)) }}</time>
          <p v-if="o.kind === 'growth' && o.reason" class="order-reason">{{ o.reason }}</p>
        </div>
        <button v-if="o.kind === 'growth' && o.state === 'PENDING'" class="shop-button primary"
          :disabled="!!busy || remaining(o.expiresAt) <= 0" @click="pay(o)">
          {{ busy === o.orderId ? '支付中…' : `支付 ${o.coinCost} 硬币` }}
        </button>
      </article>
    </section>
    <section v-if="pending" class="shop-pending" aria-live="polite"><span class="pending-dot"></span><div><strong>正在确认抢购结果</strong><p>请求已受理，确认后即可支付。刷新页面也能继续查看。</p></div><button class="shop-button" :disabled="polling" @click="poll">查询结果</button></section>
  </main></div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Coin, Reading, Present, Refresh, ArrowRight } from '@element-plus/icons-vue'
import request from '@/utils/request'
import ReadingProgress from '@/components/ReadingProgress.vue'
import ContentState from '@/components/ContentState.vue'
import SpaceSkinShop from '@/components/SpaceSkinShop.vue'
import type { ReadingProgress as Progress } from '@/utils/readingGrowth'
import { activityStatus, growthTime, orderStatus, type DecorationOrder, type GrowthActivity, type GrowthOrder } from '@/utils/growthShop'
import { confirmAction, errorMessage } from '@/utils/feedback'
import { latestRequest } from '@/utils/latestRequest'

const route = useRoute()
const activities = ref<GrowthActivity[]>([]), orders = ref<GrowthOrder[]>([])
const decorationOrders = ref<DecorationOrder[]>([])
const decorationOrdersLoading = ref(false)
const decorationOrderError = ref('')
const decorationOrderRequests = latestRequest()
const orderDate = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
const shopOrders = computed(() => [
  ...orders.value.map(order => ({ ...order, kind: 'growth' as const })),
  ...decorationOrders.value.map(order => ({ ...order, kind: 'decoration' as const }))
].sort((a, b) => (Date.parse(b.createdAt ?? '') || 0) - (Date.parse(a.createdAt ?? '') || 0)))
const tab = ref<'activities' | 'orders' | 'skins'>(route.query.tab === 'skins' ? 'skins' : 'activities')
watch(() => route.query.tab, value => {
  if (value === 'skins') tab.value = 'skins'
})
const skinShop = ref<InstanceType<typeof SpaceSkinShop>>()
const balance = ref<number>(), progress = ref<Progress>(), message = ref(''), loadError = ref(''), busy = ref(''), loading = ref(false), polling = ref(false), now = ref(Date.now())
const pending = ref<{ activityId: string; orderId: string } | null>(null)
const owner = localStorage.getItem('userId') || '', pendingKey = `growth-pending:${owner}`
const unpaidCount = computed(() => orders.value.filter(o => o.state === 'PENDING').length)
let disposed = false, timer: ReturnType<typeof setInterval> | undefined
const controller = new AbortController()
watch(tab, value => {
  if (value === 'orders') void loadDecorationOrders()
})
const remaining = (expires: string) => Math.max(0, Math.ceil((Date.parse(expires) - now.value) / 1000))
function countdown(expires: string) { const seconds = remaining(expires); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` }
function ownOrder(activity: GrowthActivity) { return orders.value.find(o => o.activityId === activity.activityId) }
function buttonLabel(a: GrowthActivity) {
  const order = ownOrder(a)
  if (order) return order.state === 'PENDING' ? '查看待支付订单' : order.state === 'PAID' ? '已兑换' : '本场已参与'
  if (pending.value?.activityId === a.activityId) return '正在确认…'
  const state = activityStatus(a, now.value)
  if (state !== '兑换中') return state
  return busy.value === a.activityId ? '提交中…' : '立即兑换'
}
function disabled(a: GrowthActivity) {
  const order = ownOrder(a)
  if (order?.state === 'PENDING') return !!busy.value
  return !!busy.value || !!pending.value || !!order || activityStatus(a, now.value) !== '兑换中'
}
async function load() {
  if (loading.value || disposed) return
  loading.value = true; loadError.value = ''
  const requests = [
    { name: '套餐', url: '/growth/activities', set: (data: GrowthActivity[]) => {
      if (!Array.isArray(data)) throw new Error('返回的套餐格式异常')
      activities.value = data
    } },
    { name: '订单', url: '/growth/orders', set: (data: GrowthOrder[]) => {
      if (!Array.isArray(data)) throw new Error('返回的订单格式异常')
      orders.value = data
    } },
    { name: '余额', url: '/growth/wallet', set: (data: { balance: number }) => {
      if (typeof data?.balance !== 'number') throw new Error('返回的余额格式异常')
      balance.value = data.balance
    } },
    { name: '阅读成长', url: '/reading/me', set: (data: Progress | null) => {
      if (data && !Array.isArray(data.rules)) throw new Error('返回的阅读成长格式异常')
      progress.value = data ?? undefined
    } }
  ]
  const results = await Promise.allSettled(requests.map(async item => { const r: any = await request.get(item.url, { signal: controller.signal }); if (!disposed) item.set(r.data) }))
  if (!disposed) { loadError.value = results.flatMap((result, index) => result.status === 'rejected' ? [`${requests[index]!.name}加载失败：${errorMessage(result.reason, '请重试')}`] : []).join('；'); loading.value = false }
}
async function loadDecorationOrders() {
  const ticket = decorationOrderRequests.begin()
  decorationOrdersLoading.value = true
  decorationOrderError.value = ''
  try {
    const response = await request.get('/user/space-customization/orders', { signal: ticket.signal })
    if (!ticket.isCurrent()) return
    if (!Array.isArray(response.data)) throw new Error('返回的装扮订单格式异常')
    decorationOrders.value = response.data
  } catch (error) {
    if (ticket.isCurrent()) decorationOrderError.value = '装扮订单加载失败。' + errorMessage(error, '请重试')
  } finally {
    if (ticket.isCurrent()) decorationOrdersLoading.value = false
  }
}
function onDecorationPurchased() {
  if (tab.value === 'orders') void loadDecorationOrders()
}
function refreshShop() {
  if (tab.value === 'skins') void skinShop.value?.load()
  else {
    void load()
    if (tab.value === 'orders') void loadDecorationOrders()
  }
}
async function action(id: string, work: () => Promise<void>) {
  if (busy.value || disposed) return
  busy.value = id; message.value = ''
  try { await work() } catch (e) { if (!disposed) message.value = errorMessage(e, '操作失败，请重试') }
  finally { if (!disposed) busy.value = '' }
}
async function grab(a: GrowthActivity) {
  if (ownOrder(a)?.state === 'PENDING') { tab.value = 'orders'; return }
  if (disabled(a)) return
  await action(a.activityId, async () => {
    const key = `growth-request:${owner}:${a.activityId}`
    let requestId = sessionStorage.getItem(key)
    if (!requestId) { requestId = crypto.randomUUID(); sessionStorage.setItem(key, requestId) }
    const result: any = await request.post(`/growth/activities/${a.activityId}/reservations`, { requestId })
    if (disposed) return
    pending.value = { activityId: a.activityId, orderId: result.data.orderId }
    sessionStorage.setItem(pendingKey, JSON.stringify(pending.value)); await poll()
  })
}
async function poll() {
  if (!pending.value || polling.value || disposed) return
  polling.value = true
  try {
    const p = pending.value, result: any = await request.get(`/growth/activities/${p.activityId}/reservations/${p.orderId}`, { signal: controller.signal })
    if (disposed) return
    if (result.data.state !== 'ACCEPTED') { pending.value = null; sessionStorage.removeItem(pendingKey); message.value = result.data.state === 'PENDING' ? '订单已创建，请在期限内支付。' : orderStatus(result.data.state); tab.value = 'orders'; await load() }
  } catch (e) { if (!disposed) message.value = errorMessage(e, '查询失败，请重试') }
  finally { if (!disposed) polling.value = false }
}
async function pay(o: GrowthOrder) {
  if (busy.value || remaining(o.expiresAt) <= 0) return
  if (!await confirmAction(`支付 ${o.coinCost} 硬币，获得 ${o.growthSeconds / 60} 分钟阅读成长？支付后自动计入阅读等级。`, '确认兑换')) return
  await action(o.orderId, async () => { const r: any = await request.post(`/growth/orders/${o.orderId}/pay`); if (!disposed) { message.value = orderStatus(r.data.state); await load() } })
}
onMounted(async () => {
  try { const value = JSON.parse(sessionStorage.getItem(pendingKey) || 'null'); if (value && typeof value.activityId === 'string' && typeof value.orderId === 'string') pending.value = value; else sessionStorage.removeItem(pendingKey) } catch { sessionStorage.removeItem(pendingKey) }
  await load(); if (disposed) return
  if (pending.value) await poll()
  if (disposed) return
  let ticks = 0
  timer = setInterval(() => { now.value = Date.now(); if (document.hidden) return; if (++ticks % 2 === 0) void poll(); if (ticks % 10 === 0 && orders.value.some(o => o.state === 'PENDING')) void load() }, 1000)
})
onUnmounted(() => { disposed = true; controller.abort(); decorationOrderRequests.cancel(); if (timer) clearInterval(timer) })
</script>

<style scoped>
.growth-page { padding-top:var(--ej-header-height);min-height:100vh;background:var(--ej-canvas);color:var(--ej-ink);font-family:var(--ej-font); }
.shop-main { max-width:1160px;padding:28px 32px 64px;margin:auto; }.shop-breadcrumb { display:flex;gap:12px;font-size:12px;color:var(--ej-muted);margin-bottom:30px; }.shop-breadcrumb a { color:inherit;text-decoration:none; }
.shop-heading { display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:28px; }.shop-eyebrow { display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ej-muted); }.shop-eyebrow svg { width:16px;height:16px; }h1 { font-size:34px;letter-spacing:-1px;margin:10px 0; }.shop-heading p:last-child { color:var(--ej-muted);font-size:14px;margin-bottom:0; }
.shop-button { display:inline-flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--ej-ink);border-radius:99px;background:var(--ej-surface);color:var(--ej-ink);padding:11px 18px;font:inherit;font-size:13px;cursor:pointer;white-space:nowrap; }.shop-button svg { width:16px;height:16px; }.shop-button.primary { background:var(--studio-lime);font-weight:650; color: var(--ej-on-color); }.shop-button:disabled { opacity:.45;cursor:not-allowed; }.shop-button:enabled:hover { box-shadow:var(--ej-shadow); }
.shop-summary { display:grid;grid-template-columns:1fr 1.2fr;gap:20px;margin-bottom:30px; }.shop-wallet { display:flex;gap:18px;align-items:center;padding:24px;border:1px solid var(--ej-ink);border-radius:18px;background:var(--ej-surface);box-shadow:var(--ej-shadow); }.wallet-icon { display:grid;place-items:center;border-radius:50%;width:56px;height:56px;background:var(--ej-accent-soft); }.wallet-icon svg { width:28px;height:28px; }.shop-wallet>div>span { font-size:12px;color:var(--ej-muted); }.shop-wallet strong { display:block;font-size:36px;margin-top:5px;line-height:1.2; }.shop-wallet strong small { font-size:12px;font-weight:400;color:var(--ej-muted);margin-left:8px; }.shop-wallet>a { margin-left:auto;font-size:12px;color:inherit;display:flex;align-items:center;gap:6px;white-space:nowrap;text-decoration:none; }.shop-wallet>a svg { width:14px;height:14px; }
.shop-tabs { display:flex;gap:24px;border-bottom:1px solid var(--ej-line);margin-bottom:28px; }.shop-tabs>button { display:flex;align-items:center;gap:8px;padding:14px 2px;border:0;border-bottom:3px solid transparent;background:transparent;font:inherit;font-size:15px;color:var(--ej-muted);cursor:pointer; }.shop-tabs>button[aria-selected=true] { border-bottom-color:var(--ej-ink);color:var(--ej-ink);font-weight:700; }.shop-tabs span { background:var(--ej-accent-soft);border-radius:99px;padding:2px 6px;font-size:11px; }
.shop-section-heading { display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px; }.shop-section-heading h2 { font-size:18px;margin:0; }.shop-section-heading>span { color:var(--ej-muted);font-size:12px; }.activity-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:22px; }.shop-product { border:1px solid var(--ej-ink);border-radius:20px;overflow:hidden;background:var(--ej-surface);box-shadow:var(--ej-shadow); }.product-banner { padding:22px 24px;background:var(--ej-accent-soft);position:relative;overflow:hidden; }.product-badge { display:inline-block;font-size:11px;border:1px solid var(--ej-line);border-radius:99px;padding:4px 9px;background:var(--ej-surface); }.product-banner>strong { display:block;font-size:60px;line-height:1.15;margin-top:18px;letter-spacing:-2px; }.product-banner>strong>span { font-size:16px;letter-spacing:0;margin-left:6px; }.product-banner>p { font-size:13px;margin:6px 0 0; }.product-art { position:absolute;right:20px;bottom:15px;transform:rotate(-15deg);opacity:.12; }.product-art svg { width:110px;height:110px; }.product-info { padding:24px; }h3 { font-size:17px;margin:0;overflow-wrap:anywhere; }.product-description { color:var(--ej-muted);font-size:12px;margin:9px 0 22px; }.product-price { display:flex;align-items:center;gap:7px; }.product-price>strong { display:flex;align-items:center;gap:6px;font-size:28px; }.product-price svg { width:23px;height:23px; }.product-price>span { color:var(--ej-muted);font-size:12px; }.product-stock { display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-top:18px; }.product-stock small { color:var(--ej-muted);font-size:10px; }.product-time { color:var(--ej-muted);font-size:11px;margin:10px 0 20px; }.product-info>.shop-button { width:100%; }.shop-rules { margin-top:28px;padding:20px 24px;border:1px solid var(--ej-line);border-radius:16px;font-size:13px; }.shop-rules p { color:var(--ej-muted);font-size:12px;line-height:1.9;margin:8px 0 0; }
.shop-order { display:flex;align-items:center;gap:20px;padding:24px;margin-bottom:16px;border:1px solid var(--ej-line);border-radius:18px;background:var(--ej-surface); }.order-icon { display:grid;place-items:center;width:52px;height:52px;flex-shrink:0;border-radius:14px;background:var(--ej-accent-soft); }.order-icon svg { width:26px;height:26px; }.order-content { flex:1;min-width:0; }.order-title { display:flex;align-items:center;flex-wrap:wrap;gap:12px; }.order-content p { font-size:13px;color:var(--ej-muted);margin:10px 0; }.order-content small { font-size:11px;color:var(--ej-muted);overflow-wrap:anywhere; }.order-state { border-radius:99px;padding:4px 9px;background:var(--ej-canvas);font-size:11px; }.order-state.pending { background:var(--ej-accent-soft); }.order-state.paid { background:var(--studio-lime-soft); color: var(--ej-on-color); }.order-content .order-reason { font-size:12px; }
.shop-pending { display:flex;align-items:center;gap:16px;padding:20px 24px;margin-top:24px;border:1px solid var(--ej-ink);border-radius:18px;background:var(--studio-lime-soft);font-size:14px; color: var(--ej-on-color); }.shop-pending>div { flex:1; }.shop-pending p { color:var(--ej-muted);font-size:12px;line-height:1.8;margin:6px 0 0; }.pending-dot { width:8px;height:8px;flex-shrink:0;border-radius:50%;background:var(--ej-accent); }.shop-feedback { padding:14px 18px;border-radius:12px;background:var(--studio-lime-soft);font-size:13px;line-height:1.8; color: var(--ej-on-color); }.shop-feedback.error { background:color-mix(in srgb, #f7ded5 var(--ej-tint), var(--ej-surface)); }.shop-feedback button { margin-left:10px;border:0;background:transparent;text-decoration:underline;color:inherit;cursor:pointer; }
.shop-button.primary, .order-state.paid, .shop-pending, .shop-pending p, .shop-feedback { color: var(--ej-on-color); }
.order-time { display:block; margin-top:4px; font-size:11px; color:var(--ej-muted); }
@media(max-width:760px) { .shop-main { padding:22px 16px 40px; }.shop-heading { align-items:flex-start; }.shop-heading h1 { font-size:28px; }.shop-heading>button { padding:9px 12px;font-size:12px; }.shop-summary { grid-template-columns:1fr;gap:14px; }.shop-order { flex-wrap:wrap;gap:14px;padding:18px; }.shop-order>.shop-button { width:100%; }.shop-section-heading { align-items:flex-start; }.shop-section-heading h2 { font-size:16px; }.shop-section-heading>span { white-space:nowrap; }.shop-pending { flex-wrap:wrap;padding:18px; }.shop-pending>.shop-button { margin-left:24px; }.activity-grid { grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); }.shop-wallet { padding:20px; } }
</style>
