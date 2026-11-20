<template>
  <div v-if="enabled" class="browser-control">
    <div class="browser-control-row">
      <button type="button" :disabled="busy || (disabled && state === 'disconnected')" @click="toggle">
        {{ state === 'disconnected' ? '连接浏览器' : '断开浏览器' }}
      </button>
      <span v-if="state === 'pending'" role="status">正在连接浏览器…</span>
      <label v-if="state === 'connected'"><input v-model="attached" type="checkbox" :disabled="disabled" /> 本轮使用浏览器</label>
      <span v-if="state === 'connected' && !multiTab">重新加载扩展并连接，即可操作多个标签页。</span>
      <span v-if="error" role="alert">{{ error }}</span>
    </div>
    <el-dialog :model-value="grant !== null" title="允许 EasyJob 操作浏览器？" width="min(420px, 92vw)"
      append-to-body :show-close="!busy" :close-on-click-modal="false" :close-on-press-escape="!busy"
      @update:model-value="closeGrant">
      <p>连接后，EasyJob 可按你的任务打开、读取和操作网页，包括填写表单和点击发送。你可以随时断开浏览器。首次使用时，Chrome 会请求网站访问权限。</p>
      <p v-if="grantError" role="alert">{{ grantError }}</p>
      <template #footer>
        <el-button :disabled="busy" @click="closeGrant(false)">取消</el-button>
        <el-button type="primary" :loading="busy" @click="authorize">允许</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import request from '@/utils/request'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'

type Status = 'disconnected' | 'pending' | 'connected'
type Extension = { sendMessage: (id: string, message: object, callback: (reply?: { accepted?: boolean; reason?: string }) => void) => void; lastError?: unknown }
type Grant = { extension: Extension; extensionId: string; ticket: string; expires: number }

const props = defineProps<{ conversationId: string | null; disabled: boolean }>()
const emit = defineEmits<{ change: [sessionId: string | null] }>()
const enabled = ref(false), busy = ref(false), error = ref('')
const attached = ref(false)
const multiTab = ref(false)
const grant = shallowRef<Grant | null>(null), grantError = ref('')
const state = ref<Status>('disconnected')
let sessionId: string | null = null, timer: ReturnType<typeof setTimeout> | undefined
let disposed = false, epoch = 0

function update(value: Status) {
  if (value !== state.value) attached.value = value === 'connected'
  state.value = value
  emit('change', value === 'connected' && attached.value ? sessionId : null)
}
watch(attached, value => emit('change', state.value === 'connected' && value ? sessionId : null))

async function poll() {
  const attempt = epoch
  if (disposed || !localStorage.getItem('userId')) return
  try {
    const { data } = await request.get('/agent/browser')
    if (disposed || attempt !== epoch) return
    enabled.value = Boolean(data?.enabled)
    multiTab.value = Boolean(data?.multiTab)
    if (sessionId && data?.sessionId === sessionId) update(data.state)
    else {
      if (state.value === 'pending') error.value = '浏览器连接未完成，请重新连接。'
      update('disconnected')
    }
  } catch {
    if (attempt === epoch && !disposed) update('disconnected')
  } finally {
    if (!disposed && attempt === epoch && sessionId && state.value !== 'disconnected') timer = setTimeout(poll, 1500)
  }
}

async function disconnect() {
  epoch++
  clearTimeout(timer)
  const attached = sessionId
  sessionId = null
  grant.value = null
  grantError.value = ''
  update('disconnected')
  if (attached) await request.delete('/agent/browser', { params: { sessionId: attached } })
}

function closeGrant(open: boolean) {
  if (!open && grant.value && !busy.value) void disconnect().catch(() => {})
}

async function toggle() {
  error.value = ''
  busy.value = true
  const attempt = epoch
  try {
    if (state.value !== 'disconnected') { await disconnect(); return }
    const extension = (window as unknown as { chrome?: { runtime?: Extension } }).chrome?.runtime
    if (!extension?.sendMessage) throw new Error('请先安装 EasyJob 浏览器扩展，再刷新此页面。')
    const { data } = await request.post('/agent/browser', { conversationId: props.conversationId })
    if (disposed || attempt !== epoch) {
      await request.delete('/agent/browser', { params: { sessionId: data.sessionId } })
      return
    }
    sessionId = data.sessionId
    grantError.value = ''
    grant.value = { extension, extensionId: data.extensionId, ticket: data.ticket, expires: Date.now() + 85000 }
  } catch (reason) {
    if (!disposed) error.value = reason instanceof Error ? reason.message : '连接浏览器失败。'
  } finally {
    busy.value = false
  }
}

async function authorize() {
  const current = grant.value
  if (!current || busy.value) return
  if (Date.now() >= current.expires) {
    await disconnect().catch(() => {})
    error.value = '授权请求已过期，请重新连接浏览器。'
    return
  }
  const attempt = epoch
  busy.value = true
  grantError.value = ''
  try {
    // No async work before sendMessage. Chrome associates the permission request with this click.
    const reply = await new Promise<{ accepted?: boolean; reason?: string } | undefined>(resolve => {
      current.extension.sendMessage(current.extensionId, { type: 'easyjob-browser-authorize', ticket: current.ticket },
        result => resolve(current.extension.lastError ? undefined : result))
    })
    if (attempt !== epoch || disposed) return
    if (!reply?.accepted) {
      grantError.value = reply?.reason === 'denied' ? '未授予网站访问权限，可再次点击允许。' :
        '无法完成授权，请确认 EasyJob 扩展已重新加载且当前窗口为普通窗口。'
      return
    }
    grant.value = null
    update('pending')
    await poll()
  } catch {
    if (attempt === epoch && !disposed) grantError.value = '无法联系 EasyJob 扩展，请重新加载扩展后再试。'
  } finally { busy.value = false }
}

function authExpired() {
  epoch++
  clearTimeout(timer)
  sessionId = null
  grant.value = null
  update('disconnected')
  enabled.value = false
}

watch(() => props.conversationId, (_, previous) => {
  if (previous && sessionId) void disconnect().catch(() => {})
})
onMounted(() => {
  eventBus.on(EVENT_AUTH_EXPIRED, authExpired)
  eventBus.on(EVENT_AUTH_CHANGED, authChanged)
  window.addEventListener('focus', refresh)
  void poll()
})
function refresh() { if (!enabled.value) void poll() }
function authChanged() { authExpired(); void poll() }
onUnmounted(() => {
  disposed = true
  eventBus.off(EVENT_AUTH_EXPIRED, authExpired)
  eventBus.off(EVENT_AUTH_CHANGED, authChanged)
  window.removeEventListener('focus', refresh)
  void disconnect().catch(() => {})
})
</script>

<style scoped>
.browser-control { padding: 6px 14px; font-size: 13px; }
.browser-control-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.browser-control button { border: 1px solid currentColor; border-radius: 20px; padding: 4px 10px; background: transparent; color: inherit; cursor: pointer; }
.browser-control button:disabled { opacity: .5; cursor: default; }
</style>
