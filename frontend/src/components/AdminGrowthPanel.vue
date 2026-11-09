<template>
  <section class="growth-admin">
    <div class="growth-admin-toolbar"><p>每份 10 硬币兑换 30 分钟阅读成长，每人每场限购一份。</p><div><RouterLink to="/growth-shop">查看商城 ↗</RouterLink><button class="ink-button" @click="openCreate">＋ 新建活动</button></div></div>
    <ContentState v-if="loading && !rows.length" kind="loading" title="正在加载商城活动" />
    <ContentState v-else-if="error" kind="error" title="活动暂时无法加载" :description="error" @retry="reload" />
    <ContentState v-else-if="!rows.length" kind="empty" title="还没有商城活动" description="创建活动并发布后，用户就能在硬币商城参与兑换。" />
    <div v-else class="growth-admin-list">
      <article v-for="row in rows" :key="row.activityId" class="growth-admin-card">
        <div class="activity-heading"><h2>{{ row.title }}</h2><span class="state-tag" :class="row.state.toLowerCase()">{{ activityStatus(row, now) }}</span></div>
        <p class="activity-offer">{{ row.coinPrice }} 硬币 <span>兑换</span> {{ row.growthSeconds / 60 }} 分钟成长</p>
        <dl><div><dt>剩余名额 / 总名额</dt><dd>{{ row.availableStock }} / {{ row.totalStock }} 份</dd></div><div><dt>活动时间</dt><dd>{{ growthTime(row.startsAt) }} — {{ growthTime(row.endsAt) }}</dd></div><div><dt>支付期限</dt><dd>下单后 {{ row.paySeconds }} 秒</dd></div></dl>
        <div class="activity-actions">
          <button v-if="row.state === 'DRAFT'" class="ink-button" :disabled="!!busy || now >= Date.parse(row.endsAt)" @click="manage(row, 'activate')">{{ busy === row.activityId ? '发布中…' : '发布活动' }}</button>
          <button v-else-if="row.state === 'ACTIVE'" :disabled="!!busy" @click="manage(row, 'pause')">下架活动</button>
          <button v-else class="ink-button" :disabled="!!busy || now >= Date.parse(row.endsAt)" @click="manage(row, 'resume')">对账并重新上架</button>
          <button :disabled="!!busy" @click="audit(row)">查看对账</button>
          <small>{{ row.state === 'DRAFT' ? '发布前仅管理员可见' : '名额显示以已确认订单为准' }}</small>
        </div>
      </article>
    </div>

    <el-dialog v-model="creating" title="新建商城活动" width="min(560px, 94vw)" align-center append-to-body class="ej-dialog" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="closeCreate">
      <form id="growth-create-form" class="growth-form" @submit.prevent="create(true)">
        <div class="offer-preview"><Coin /><div><strong>30 分钟阅读成长</strong><span>10 硬币 / 份 · 成长永久累计</span></div></div>
        <fieldset :disabled="!!busy">
          <label>活动名称<input v-model="form.title" required maxlength="80" placeholder="例如：周末阅读成长专场" /></label>
          <div class="growth-form-pair"><label>活动名额（份）<input v-model.number="form.stock" required type="number" min="1" max="100000" step="1" /></label><label>支付期限（秒）<input v-model.number="form.paySeconds" required type="number" min="10" max="600" step="1" /></label></div>
          <label>开始时间<input v-model="form.startsAt" required type="datetime-local" /></label>
          <label>结束时间<input v-model="form.endsAt" required type="datetime-local" /></label>
        </fieldset>
        <p class="growth-form-hint">活动最长 7 天。发布后按开始时间开放兑换；未支付订单超时自动关闭并归还名额，同一用户仍不能重复参与本场。</p>
        <p v-if="formError" role="alert" class="growth-form-error">{{ formError }}</p>
      </form>
      <template #footer><div class="growth-dialog-actions"><button :disabled="!!busy" @click="closeCreate()">取消</button><button :disabled="!!busy" @click="create(false)">保存草稿</button><button class="ink-button" form="growth-create-form" type="submit" :disabled="!!busy">{{ busy === 'create' ? '提交中…' : '发布活动' }}</button></div></template>
    </el-dialog>

    <el-dialog v-model="auditing" title="活动库存对账" width="min(620px, 94vw)" align-center append-to-body class="ej-dialog">
      <ContentState v-if="auditLoading" kind="loading" title="正在核对库存与订单" />
      <ContentState v-else-if="auditError" kind="error" title="暂时无法完成对账" :description="auditError" @retry="loadAudit" />
      <div v-else-if="report" class="audit-report"><h3>{{ report.activity.title }}</h3><p class="audit-result" :class="{ ready: auditReady(report) }">{{ auditReady(report) ? '库存与订单记录一致' : '存在待处理项，请核对后恢复活动' }}</p><dl><div><dt>数据库库存口径</dt><dd>{{ report.databaseStockConsistent ? '一致' : '不一致' }}</dd></div><div><dt>数据库剩余名额</dt><dd>{{ report.activity.availableStock }} 份</dd></div><div><dt>Redis 剩余名额</dt><dd>{{ report.redisStock === null ? '缺失' : `${report.redisStock} 份` }}</dd></div><div><dt>未确认的抢购记录</dt><dd>{{ report.unconfirmedReservations }} 条</dd></div><div><dt>待完成的补偿 / 通知</dt><dd>{{ report.pendingEffects }} 条</dd></div><div><dt>预占凭据</dt><dd>{{ report.missingReceipts ? '存在缺失' : '完整' }}</dd></div><div v-for="group in report.ordersByState" :key="group.state"><dt>{{ orderStatus(group.state) }}</dt><dd>{{ group.amount }} 单</dd></div></dl><p>重新上架时，服务端会再次对账；未通过校验将保持下架状态。</p></div>
      <template #footer><button @click="auditing = false">关闭</button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { Coin } from '@element-plus/icons-vue'
import ContentState from './ContentState.vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import { confirmAction, errorMessage, notify } from '@/utils/feedback'
import { activityStatus, auditReady, growthTime, localDateTime, orderStatus, type GrowthActivity, type GrowthAudit } from '@/utils/growthShop'

const rows = ref<GrowthActivity[]>([]), loading = ref(false), error = ref(''), busy = ref(''), now = ref(Date.now())
const creating = ref(false), formError = ref(''), form = ref(defaultForm())
const auditing = ref(false), auditLoading = ref(false), auditError = ref(''), report = ref<GrowthAudit>(), auditId = ref('')
const gate = latestRequest(), auditGate = latestRequest()
let disposed = false, timer: ReturnType<typeof setInterval> | undefined
function defaultForm() { return { title: '30 分钟阅读成长套餐', stock: 100, paySeconds: 120, startsAt: localDateTime(new Date(Date.now() + 300000)), endsAt: localDateTime(new Date(Date.now() + 86400000)) } }
async function reload() {
  const run = gate.begin(); loading.value = true; error.value = ''
  try { const r: any = await request.get('/growth/admin/activities', { signal: run.signal }); if (run.isCurrent() && !disposed) rows.value = r.data }
  catch (e) { if (run.isCurrent() && !disposed) error.value = errorMessage(e, '加载失败，请重试') }
  finally { if (run.isCurrent() && !disposed) loading.value = false }
}
function openCreate() { form.value = defaultForm(); formError.value = ''; creating.value = true }
function closeCreate(done?: () => void) { if (busy.value) return; creating.value = false; done?.() }
async function create(publish: boolean) {
  if (busy.value) return
  const f = form.value, start = Date.parse(f.startsAt), end = Date.parse(f.endsAt)
  if (!f.title.trim() || !Number.isInteger(f.stock) || f.stock < 1 || f.stock > 100000 || !Number.isInteger(f.paySeconds) || f.paySeconds < 10 || f.paySeconds > 600) { formError.value = '请填写活动名称、1～100000 份名额和 10～600 秒支付期限。'; return }
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || end <= Date.now() || end - start > 604800000) { formError.value = '结束时间需晚于开始时间和当前时间，活动最长 7 天。'; return }
  busy.value = 'create'; formError.value = ''
  let createdId = ''
  try {
    const r: any = await request.post('/growth/admin/activities', { ...f, title: f.title.trim(), startsAt: new Date(start).toISOString(), endsAt: new Date(end).toISOString() })
    createdId = r.data.activityId
    if (publish) await request.post(`/growth/admin/activities/${createdId}/activate`)
    if (!disposed) { creating.value = false; notify.success(publish ? '活动已发布，到开始时间自动开放兑换' : '活动草稿已保存'); await reload() }
  } catch (e) {
    if (!disposed) {
      if (createdId) { creating.value = false; notify.error(`草稿已保存，发布失败：${errorMessage(e, '请在活动列表重试发布')}`); await reload() }
      else formError.value = errorMessage(e, '创建失败，请重试')
    }
  } finally { if (!disposed) busy.value = '' }
}
async function manage(row: GrowthActivity, operation: 'activate' | 'pause' | 'resume') {
  if (busy.value) return
  const label = operation === 'activate' ? '发布活动' : operation === 'pause' ? '下架活动' : '重新上架'
  const note = operation === 'pause' ? '下架后停止接受新兑换，已有订单仍可在期限内支付。尚未确认的抢购可能被退回。' : operation === 'resume' ? '将校验库存与未完成记录，通过后重新开放兑换。' : '发布后用户可在商城看到活动，并在活动时间内参与兑换。'
  if (!await confirmAction(`《${row.title}》：${note}`, label, { confirmText: `确认${label}` })) return
  if (busy.value || disposed) return
  busy.value = row.activityId
  try { await request.post(`/growth/admin/activities/${row.activityId}/${operation}`); if (!disposed) { notify.success(`${label}成功`); await reload() } }
  catch (e) { if (!disposed) notify.error(errorMessage(e, `${label}失败，请重试`)) }
  finally { if (!disposed) busy.value = '' }
}
function audit(row: GrowthActivity) { auditId.value = row.activityId; report.value = undefined; auditing.value = true; void loadAudit() }
async function loadAudit() {
  const run = auditGate.begin(); auditLoading.value = true; auditError.value = ''
  try { const r: any = await request.get(`/growth/admin/activities/${auditId.value}/audit`, { signal: run.signal }); if (run.isCurrent() && !disposed) report.value = r.data }
  catch (e) { if (run.isCurrent() && !disposed) auditError.value = errorMessage(e, '对账失败，请重试') }
  finally { if (run.isCurrent() && !disposed) auditLoading.value = false }
}
defineExpose({ reload })
onMounted(() => { void reload(); timer = setInterval(() => { now.value = Date.now() }, 1000) })
onUnmounted(() => { disposed = true; gate.cancel(); auditGate.cancel(); if (timer) clearInterval(timer) })
</script>

<style scoped>
.growth-admin { font-size:13px; }
.growth-admin-toolbar,.growth-admin-toolbar>div,.activity-heading,.activity-actions { display:flex;align-items:center;gap:12px;justify-content:space-between; }
.growth-admin-toolbar { margin-bottom:22px;flex-wrap:wrap; }
.growth-admin-toolbar p { margin:0;color:var(--ej-muted);line-height:1.8; }
.growth-admin-toolbar a { color:inherit;white-space:nowrap; }
button { padding:10px 16px;border:1px solid var(--ej-line);border-radius:99px;background:var(--ej-surface);color:var(--ej-ink);font:inherit;font-size:13px;cursor:pointer; }
button:disabled { opacity:.45;cursor:not-allowed; }
.ink-button { background:var(--ej-ink);color:var(--ej-surface);border-color:var(--ej-ink); }
.growth-admin-list { display:grid;gap:16px; }
.growth-admin-card { background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:18px;padding:24px; }
h2 { font-size:17px;margin:0;overflow-wrap:anywhere; }
.state-tag { border-radius:99px;padding:5px 10px;font-size:11px;background:var(--ej-canvas);white-space:nowrap; }
.state-tag.active { background:var(--studio-lime-soft); }.state-tag.paused { background:var(--ej-accent-soft); }
.activity-offer { font-size:17px;font-weight:650;margin:22px 0; }.activity-offer span { font-size:12px;color:var(--ej-muted);font-weight:400;margin:0 6px; }
dl { margin:0;display:grid;grid-template-columns:1fr 2fr 1fr;gap:18px; }dt { color:var(--ej-muted);font-size:12px; }dd { margin:8px 0 0;line-height:1.6; }
.activity-actions { justify-content:flex-start;flex-wrap:wrap;border-top:1px solid var(--ej-hairline);padding-top:18px;margin-top:20px; }.activity-actions small { color:var(--ej-muted);margin-left:auto; }
.growth-form fieldset { display:grid;gap:18px;border:0;margin:20px 0;padding:0; }.growth-form label { display:grid;gap:8px;font-size:13px;min-width:0; }.growth-form input { width:100%;min-width:0;box-sizing:border-box;padding:11px;border:1px solid var(--ej-line);border-radius:10px;background:var(--ej-canvas);font:inherit;color:var(--ej-ink); }.growth-form-pair { display:grid;grid-template-columns:1fr 1fr;gap:16px; }
.offer-preview { display:flex;align-items:center;gap:14px;background:var(--studio-lime-soft);border-radius:12px;padding:18px; }.offer-preview svg { width:32px;height:32px; }.offer-preview strong,.offer-preview span { display:block; }.offer-preview span { font-size:12px;margin-top:7px;color:var(--ej-muted); }
.growth-form-hint,.audit-report>p { font-size:12px;color:var(--ej-muted);line-height:1.8; }.growth-form-error { color:#b44a36;font-size:13px; }.growth-dialog-actions { display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px; }
.audit-report h3 { margin-top:0; }.audit-report dl { grid-template-columns:1fr;gap:0; }.audit-report dl>div { display:flex;justify-content:space-between;gap:20px;padding:12px 0;border-bottom:1px solid var(--ej-hairline); }.audit-report dd { margin:0; }.audit-report .audit-result { padding:12px;background:#f7ded5;border-radius:10px;color:var(--ej-ink); }.audit-report .audit-result.ready { background:var(--studio-lime-soft); }
@media(max-width:760px) { .growth-admin-card { padding:18px; }dl { grid-template-columns:1fr;gap:12px; }dd { margin-top:4px; }.activity-actions small { width:100%;margin:0; }.activity-heading { align-items:flex-start; } }
</style>
