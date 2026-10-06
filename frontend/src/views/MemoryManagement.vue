<template>
  <div class="memory-page">
    <nav class="navbar"><RouterLink class="logo" to="/">EasyJob</RouterLink><span class="page-title">长期记忆</span><AppNavigation /></nav>
    <main class="memory-layout">
      <header class="memory-heading"><div><h1>让助手更懂你</h1><p>查看它记住了什么，也由你决定保留什么。修改将在下一次提问时生效。</p></div><RouterLink class="memory-button" to="/ai-chat">回到对话 ↗</RouterLink></header>
      <ContentState v-if="loading && !data" kind="loading" title="正在读取记忆" />
      <ContentState v-else-if="loadError" kind="error" title="记忆暂时无法加载" :description="loadError" @retry="load()" />
      <template v-else-if="data">
        <section v-if="data.write_jobs?.length" class="write-status" aria-live="polite">
          <p>对话中的记忆保存状态 <span>业务任务独立执行，保存冲突不会覆盖原有记录。</span></p>
          <div v-for="job in data.write_jobs" :key="job.id"><span>{{ writeStatusLabel(job.status) }}</span><time>{{ formatDate(job.updated_at) }}</time></div>
        </section>
        <section class="memory-card profile-card">
          <div class="section-heading"><div><span class="memory-eyebrow">01 / 用户画像</span><h2>背景与偏好</h2></div><button class="memory-button" :disabled="busy || loading" @click="startProfile">{{ editingProfile ? '重新编辑' : '编辑画像' }}</button></div>
          <form v-if="editingProfile" class="profile-form" @submit.prevent="saveProfile">
            <label>关注领域<input v-model="profileForm.topics" maxlength="4039" placeholder="Java, Redis, Agent（逗号分隔）"><small>你长期关注、想学或想写的方向，最多40项；不代表熟练程度。</small></label>
            <label>学习背景<input v-model="profileForm.experience" maxlength="100" placeholder="例如：Python 新手，从事 Java 后端开发"><small>写明对应领域，帮助助手调整讲解深度。</small></label>
            <label>回答偏好 <small>英文小写键名，如 language、detail、code_language</small><div v-for="(pref, index) in profileForm.preferences" :key="index" class="preference-row"><input v-model="pref.key" maxlength="40" aria-label="偏好名称" placeholder="language"><input v-model="pref.value" maxlength="1000" aria-label="偏好内容" placeholder="中文"><button type="button" :disabled="busy" @click="profileForm.preferences.splice(index, 1)" aria-label="移除偏好">×</button></div></label>
            <button type="button" class="text-button" :disabled="busy || profileForm.preferences.length >= 20" @click="profileForm.preferences.push({ key: '', value: '' })">＋添加偏好</button>
            <div class="form-actions"><button class="memory-button primary" :disabled="busy">{{ busy ? '保存中…' : '保存修改' }}</button><button type="button" class="memory-button" :disabled="busy" @click="editingProfile = false">取消</button><button type="button" class="text-button danger" :disabled="busy" @click="clearProfile">清空画像</button></div>
          </form>
          <div v-else class="profile-grid">
            <div class="profile-topics"><span>关注领域</span><p>{{ data.profile.topics?.join(' · ') || '尚未记录' }}</p><small>长期关注、想学或想写的方向</small></div>
            <div><span>学习背景</span><p>{{ data.profile.experience === 'unknown' ? '尚未记录' : data.profile.experience }}</p></div>
            <div><span>回答偏好</span><p v-for="(value, key) in data.profile.preferences" :key="key">{{ preferenceLabel(key) }}：{{ value }}</p><p v-if="!Object.keys(data.profile.preferences || {}).length">尚未记录</p></div>
          </div>
          <p class="memory-meta">更新于 {{ formatDate(data.profile_updated_at) }} · 明确表达背景或长期偏好后更新</p>
        </section>
        <section class="memory-records">
          <div class="section-heading"><div><span class="memory-eyebrow">02 / 记忆记录</span><h2>约束与已确认决策</h2></div><button class="text-button" :disabled="busy || loading" @click="load()">刷新</button></div>
          <div class="memory-tabs" role="group" aria-label="记忆类型"><button v-for="tab in tabs" :key="tab.key" :class="{ active: selected === tab.key }" @click="selectType(tab.key)">{{ tab.label }}</button></div>
          <p class="memory-explanation">对话中的画像、约束和已确认决策按明确表达提交后台保存，成功后生效。普通问答不会自动保存为长期记忆；旧事件仅供查看，不参与召回。</p>
          <ContentState v-if="!visibleMemories.length" kind="empty" title="这里还没有记忆" description="可以在对话中明确告诉助手需要记住的背景、约束或已确认决定。" />
          <article v-for="memory in visibleMemories" :key="memory.memory_id" class="memory-card record-card" :class="{ inactive: memory.memory_type === 'event' || memory.status !== 'active' }">
            <div class="record-top"><span class="memory-kind">{{ typeLabel(memory.memory_type) }}</span><span>{{ memory.memory_type === 'event' ? '已归档 · 不参与召回' : `${memory.scope === 'user' ? '跨会话' : '仅所属会话'} · ${memory.status === 'active' ? '使用中' : '已停用'}` }}</span></div>
            <form v-if="editingId === memory.memory_id" @submit.prevent="changeRecord(memory, editContent, memory.status === 'active', editVersion)"><textarea v-model="editContent" :disabled="busy" maxlength="1000" rows="4" aria-label="记忆内容"></textarea><small v-if="memory.memory_key === 'web_search'">联网约束填 deny（禁止）或 allow（允许）。</small><div class="form-actions"><button class="memory-button primary" :disabled="busy">保存</button><button type="button" class="memory-button" :disabled="busy" @click="editingId = ''">取消</button></div></form>
            <p v-else class="record-content">{{ memory.memory_key === 'web_search' ? (memory.content === 'deny' ? '禁止联网搜索' : '允许联网搜索') : memory.content }}</p>
            <details v-if="memory.source_quote"><summary>查看原话</summary><blockquote>{{ memory.source_quote }}</blockquote></details>
            <div class="record-footer"><div class="memory-meta"><RouterLink v-if="memory.source_title" :to="{ path: '/ai-chat', query: { conversationId: memory.source_conversation_id } }">来源：{{ memory.source_title }} ↗</RouterLink><span v-else>来源会话已不可用</span><span>更新于 {{ formatDate(memory.update_time) }}</span></div><div class="record-actions"><button v-if="memory.memory_type !== 'event'" class="text-button" :disabled="busy || loading" @click="editingId = memory.memory_id; editContent = memory.content; editVersion = memory.version">编辑</button><button v-if="memory.memory_type !== 'event'" class="text-button" :disabled="busy || loading" @click="changeRecord(memory, memory.content, memory.status !== 'active')">{{ memory.status === 'active' ? '停用' : '启用' }}</button><button class="text-button danger" :disabled="busy || loading" @click="deleteRecord(memory)">删除</button></div></div>
          </article>
          <button v-if="data.next_cursor" class="memory-button load-more" :disabled="loading || busy" @click="load(true)">{{ loading ? '加载中…' : '加载更多记忆' }}</button>
        </section>
      </template>
    </main>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AppNavigation from '@/components/AppNavigation.vue'
import ContentState from '@/components/ContentState.vue'
import request from '@/utils/request'
import { notify, errorMessage, confirmAction } from '@/utils/feedback'
import { latestRequest } from '@/utils/latestRequest'
type Memory = { memory_id: string; version: string; memory_type: string; memory_key: string; content: string; status: string; scope: string; source_quote?: string; source_title?: string; source_conversation_id?: string; update_time?: string }
type Overview = { profile: { topics: string[]; experience: string; preferences: Record<string, string> }; profile_version: string; profile_updated_at?: string; memories: Memory[]; next_cursor?: string; extraction: { enabled: boolean }; write_jobs?: { id: string; status: string; updated_at?: string }[] }
const data = ref<Overview>(), loading = ref(false), loadError = ref(''), busy = ref(false), requests = latestRequest()
const selected = ref('all'), editingId = ref(''), editContent = ref(''), editVersion = ref(''), editingProfile = ref(false)
const profileForm = ref({ version: '', topics: '', experience: 'unknown', preferences: [] as { key: string; value: string }[] })
const tabs = [{ key: 'all', label: '全部' }, { key: 'constraint', label: '约束' }, { key: 'decision', label: '决策' }, { key: 'event', label: '旧事件（归档）' }]
const visibleMemories = computed(() => data.value?.memories.filter(m => selected.value === 'all' ? ['constraint', 'decision'].includes(m.memory_type) : m.memory_type === selected.value) || [])
function selectType(kind: string) {
  if (selected.value === kind) return
  selected.value = kind; editingId.value = ''; data.value = undefined
  load()
}
function typeLabel(type: string) { return tabs.find(t => t.key === type)?.label || '记忆' }
function preferenceLabel(key: string) { return ({ language: '回答语言', detail: '讲解详细程度', code_language: '代码示例语言', style: '表达风格' } as Record<string, string>)[key] || key }
function formatDate(value?: string) { return value ? new Date(value.replace(' ', 'T')).toLocaleString('zh-CN', { hour12: false }) : '尚未记录' }
function writeStatusLabel(status: string) { return ({ pending: '正在后台保存', succeeded: '已保存到长期记忆', conflict: '存在冲突，未覆盖旧记忆，请查看并确认', failed: '保存失败，可在对话中重新提交', cancelled: '已取消保存' } as Record<string, string>)[status] || '保存状态待确认' }
async function load(append = false) {
  const ticket = requests.begin(); loading.value = true; loadError.value = ''
  try {
    const result: any = await request.get('/agent/memory', { params: { kind: selected.value, before: append ? data.value?.next_cursor : undefined }, signal: ticket.signal })
    if (!ticket.isCurrent()) return
    const overview: Overview = result.data
    if (append && data.value) overview.memories = [...data.value.memories, ...overview.memories]
    data.value = overview
  } catch (e) { if (ticket.isCurrent()) loadError.value = errorMessage(e) }
  finally { if (ticket.isCurrent()) loading.value = false }
}
function startProfile() {
  if (!data.value) return
  const p = data.value.profile
  profileForm.value = { version: data.value.profile_version, topics: p.topics.join(', '), experience: p.experience, preferences: Object.entries(p.preferences).map(([key, value]) => ({ key, value: String(value) })) }
  editingProfile.value = true
}
async function saveProfile() {
  if (busy.value) return
  const form = profileForm.value
  const keys = form.preferences.map(p => p.key.trim())
  if (new Set(keys).size !== keys.length) { notify.warning('偏好名称不能重复'); return }
  busy.value = true
  try {
    const split = (v: string) => [...new Set(v.split(/[,，]/).map(s => s.trim()).filter(Boolean))]
    await request.put('/agent/memory/profile', { version: form.version, topics: split(form.topics), experience: form.experience.trim() || 'unknown', preferences: Object.fromEntries(form.preferences.map(p => [p.key.trim(), p.value.trim()])) })
    editingProfile.value = false; notify.success('画像已更新'); await load()
  } catch (e) { notify.error(errorMessage(e)) }
  finally { busy.value = false }
}
async function clearProfile() {
  if (!await confirmAction('清空关注领域、学习背景和全部回答偏好？', '清空画像')) return
  profileForm.value = { ...profileForm.value, topics: '', experience: 'unknown', preferences: [] }; await saveProfile()
}
async function changeRecord(memory: Memory, content: string, active: boolean, version = memory.version) {
  if (busy.value || loading.value) return
  busy.value = true
  try { await request.put(`/agent/memory/records/${memory.memory_id}`, { version, content, active }); editingId.value = ''; notify.success(active ? '记忆已更新' : '记忆已停用'); await load() }
  catch (e) { notify.error(errorMessage(e)) }
  finally { busy.value = false }
}
async function deleteRecord(memory: Memory) {
  if (busy.value) return
  busy.value = true
  try { if (!await confirmAction('删除这条记忆？删除后助手不再使用它。', '删除记忆')) return; await request.delete(`/agent/memory/records/${memory.memory_id}`, { params: { version: memory.version } }); notify.success('记忆已删除'); await load() }
  catch (e) { notify.error(errorMessage(e)) }
  finally { busy.value = false }
}
let writePoll: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  load()
  writePoll = setInterval(() => {
    if (!document.hidden && !loading.value && !busy.value && !editingProfile.value && !editingId.value
        && data.value?.write_jobs?.some(job => job.status === 'pending')) load()
  }, 3000)
})
onUnmounted(() => { requests.cancel(); if (writePoll) clearInterval(writePoll) })
</script>
<style scoped>
.write-status { margin-bottom: 24px; border: 1px solid #17171435; border-radius: 18px; padding: 18px 24px; background: #f7f7ec; }.write-status p { margin: 0 0 12px; font-weight: 600; }.write-status p span { display: block; margin-top: 6px; color: #77796f; font-size: 13px; font-weight: 400; }.write-status div { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; padding: 7px 0; font-size: 13px; }.write-status time { color: #85887d; }
.profile-topics { grid-column: 1 / -1; }
.memory-page { min-height: 100vh; color: #171714; }
.navbar { display: flex; align-items: center; gap: 24px; padding: 0 3.2vw; height: 96px; border-bottom: 1px solid #17171430; background: #f1efe8; }
.logo { color: inherit; font-size: 26px; font-weight: 850; text-decoration: none; }.page-title { flex: 1; color: #77786e; }
.memory-layout { max-width: 1140px; padding: 44px 28px 80px; margin: auto; }
.memory-heading,.section-heading { display: flex; gap: 18px; align-items: center; justify-content: space-between; }.memory-heading { margin-bottom: 32px; }.memory-heading h1 { font-size: 28px; margin: 0 0 10px; }.memory-heading p,.memory-explanation { font-size: 14px; color: #76796e; line-height: 1.8; }.memory-card { background: #fffdf5; border: 1px solid #171714; border-radius: 22px; padding: 26px; box-shadow: 4px 5px 0 #1717140b; }.profile-card { margin-bottom: 36px; }.memory-eyebrow { font-size: 11px; letter-spacing: 1px; color: #74776c; }.section-heading h2 { font-size: 20px; margin: 8px 0 0; }.profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px 32px; margin: 26px 0; }.profile-grid span { font-size: 13px; color: #76796e; }.profile-grid p { margin: 8px 0; line-height: 1.7; overflow-wrap: anywhere; }.memory-meta { display: flex; gap: 8px; flex-direction: column; font-size: 12px; color: #85887d; margin: 0; }.memory-meta a { color: #676d5a; text-decoration: none; }.memory-button { display: inline-block; padding: 10px 18px; border: 1px solid #171714; background: #fffdf5; color: #171714; border-radius: 24px; cursor: pointer; text-decoration: none; font-size: 14px; white-space: nowrap; }.memory-button.primary { background: #ccff45; }.memory-button:hover { background: #e9eddf; }.memory-button:disabled,.text-button:disabled { opacity: .5; cursor: wait; }.text-button { border: 0; background: transparent; color: #5b654d; font-size: 13px; cursor: pointer; padding: 8px; }.danger { color: #ae503f; }.memory-tabs { display: flex; gap: 10px; margin-top: 24px; }.memory-tabs button { border: 1px solid transparent; padding: 8px 16px; border-radius: 24px; background: transparent; cursor: pointer; }.memory-tabs .active { background: #ccff45; border-color: #171714; }.record-card { margin: 16px 0; transition: transform .2s, box-shadow .2s; }.record-card:hover { transform: translateY(-2px); box-shadow: 4px 7px 0 #17171412; }.record-top { display: flex; align-items: center; gap: 12px; font-size: 12px; color: #76796e; }.memory-kind { border: 1px solid #9fa78e; color: #414b31; border-radius: 20px; padding: 4px 10px; background: #eef2e5; }.inactive .memory-kind { background: #eeeae2; color: #777; }.record-content { line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; margin: 20px 0; }.record-footer { display: flex; justify-content: space-between; gap: 20px; border-top: 1px solid #17171418; padding-top: 16px; margin-top: 18px; }.record-actions { display: flex; align-items: center; }summary { font-size: 13px; cursor: pointer; color: #707763; }blockquote { border-left: 2px solid #c0caa9; padding-left: 14px; margin: 12px 0; font-size: 14px; line-height: 1.7; color: #77796f; }.profile-form { margin-top: 24px; display: grid; gap: 16px; }.profile-form label { font-size: 14px; display: grid; gap: 8px; }.profile-form small,small { color: #85887d; font-size: 12px; }input,textarea { width: 100%; box-sizing: border-box; border: 1px solid #17171435; background: #f4f3ec; padding: 12px; border-radius: 12px; color: #171714; font: inherit; }input:focus,textarea:focus { outline: 2px solid #bde64d; outline-offset: 2px; }.preference-row { display: grid; grid-template-columns: 150px 1fr 30px; gap: 10px; }.preference-row button { border: 0; background: none; cursor: pointer; }.form-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }.load-more { display: block; margin: 26px auto; }
@media(max-width: 720px) { .navbar { height: auto; min-height: 82px; flex-wrap: wrap; padding: 18px; gap: 10px; }.memory-layout { padding: 26px 16px 60px; }.memory-heading { align-items: flex-start; flex-direction: column; }.memory-card { padding: 20px; }.profile-grid { grid-template-columns: 1fr; }.record-footer { flex-direction: column; gap: 12px; }.preference-row { grid-template-columns: 90px 1fr 24px; gap: 6px; }.memory-tabs { flex-wrap: wrap; } }
@media(prefers-reduced-motion: reduce) { .record-card { transition: none; }.record-card:hover { transform: none; } }
</style>
