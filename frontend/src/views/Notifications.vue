<template>
  <div class="notify-page">
    <StarBackground />

    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="logo" @click="$router.push('/')">
        <svg class="logo-icon" viewBox="0 0 1024 1024" fill="currentColor">
          <path d="M512 1024c282.771692 0 512-229.228308 512-512S794.771692 0 512 0 0 229.228308 0 512s229.228308 512 512 512z m0-59.076923C261.858462 964.923077 59.076923 762.141538 59.076923 512S261.858462 59.076923 512 59.076923s452.923077 202.781538 452.923077 452.923077-202.781538 452.923077-452.923077 452.923077z"/>
          <path d="M464.945231 748.642462c15.399385 3.042462 31.133538 4.588308 47.054769 4.588307 133.228308 0 241.230769-108.002462 241.230769-241.230769S645.228308 270.769231 512 270.769231 270.769231 378.771692 270.769231 512c0 15.921231 1.545846 31.655385 4.588307 47.054769a24.615385 24.615385 0 0 0 48.295385-9.550769A193.053538 193.053538 0 0 1 320 512c0-106.043077 85.956923-192 192-192S704 405.956923 704 512 618.043077 704 512 704c-12.701538 0-25.245538-1.230769-37.494154-3.652923a24.615385 24.615385 0 1 0-9.550769 48.295385z"/>
          <path d="M512 512m-78.769231 0a78.769231 78.769231 0 1 0 157.538462 0 78.769231 78.769231 0 1 0-157.538462 0Z"/>
          <path d="M510.385231 498.294154C396.465231 543.123692 320 653.351385 320 777.846154a24.615385 24.615385 0 1 0 49.230769 0 251.145846 251.145846 0 0 1 159.182769-233.737846 24.615385 24.615385 0 0 0-18.018461-45.814154z"/>
        </svg>
        <span class="logo-text">EasyJob</span>
      </div>
      <div class="page-title">消息通知</div>
      <div class="nav-right">
        <button class="nav-btn" @click="$router.push('/')">返回首页</button>
      </div>
    </nav>

    <div class="main">
      <!-- 顶部分类 Tab + 操作 -->
      <div class="toolbar">
        <div class="tabs">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            :class="['tab', { active: activeTab === tab.value }]"
            @click="switchTab(tab.value)"
          >
            {{ tab.label }}
            <span v-if="tab.value === null && notifyUnreadCount > 0" class="tab-badge">
              {{ notifyUnreadCount > 99 ? '99+' : notifyUnreadCount }}
            </span>
          </button>
        </div>
        <button
          class="btn-mark-all"
          :disabled="notifyUnreadCount === 0"
          @click="markAllRead"
        >
          全部已读
        </button>
      </div>

      <!-- 列表 -->
      <div v-if="loading" class="state-block">加载中...</div>
      <div v-else-if="items.length === 0" class="state-block empty">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>
          </svg>
        </div>
        <p>{{ emptyText }}</p>
      </div>
      <div v-else class="list">
        <div
          v-for="n in items"
          :key="n.notificationId"
          :class="['notify-card', { unread: n.isRead === 0 }]"
          @click="openNotify(n)"
        >
          <img
            :src="getAvatarUrl(n.senderAvatar)"
            :alt="n.senderNickname || '用户'"
            class="avatar"
            @click.stop="goToUserSpace(n.senderId)"
            @error="handleAvatarError"
          >
          <div class="body">
            <div class="line-1">
              <span class="sender" @click.stop="goToUserSpace(n.senderId)">
                {{ n.senderNickname || '有人' }}
              </span>
              <span class="verb">{{ n.content }}</span>
              <span class="time">{{ formatTime(n.createTime) }}</span>
            </div>
            <div v-if="n.articleTitle" class="line-2 article-title">
              《{{ n.articleTitle }}》
            </div>
            <div v-if="n.targetPreview" class="line-2 target-preview">
              "{{ n.targetPreview }}"
            </div>
          </div>
          <span v-if="n.isRead === 0" class="unread-dot"></span>
        </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="pagination">
          <button class="page-btn" :disabled="page === 1" @click="changePage(page - 1)">上一页</button>
          <span class="page-info">{{ page }} / {{ totalPages }}</span>
          <button class="page-btn" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import StarBackground from '@/components/StarBackground.vue'
import request from '@/utils/request'
import {
  notifyUnreadCount,
  latestNotify,
  fetchNotifyUnreadCount,
  type NotifyMessage
} from '@/utils/notification'

const router = useRouter()

// Tab：null = 全部；0 = 未读；或按 type 分类
const tabs = [
  { label: '全部', value: null as number | null },
  { label: '未读', value: 0 },
  { label: '评论/回复', value: 1 },
  { label: '点赞', value: 2 },
  { label: '收藏', value: 3 },
  { label: '关注', value: 4 }
]
const activeTab = ref<number | null>(null)

const items = ref<NotifyMessage[]>([])
const loading = ref(false)
const page = ref(1)
const size = 20
const total = ref(0)
const totalPages = computed(() => Math.ceil(total.value / size) || 1)

const emptyText = computed(() => {
  if (activeTab.value === 0) return '暂无未读通知'
  if (activeTab.value === null) return '暂无通知'
  return '该分类下暂无通知'
})

function switchTab(v: number | null) {
  if (activeTab.value === v) return
  activeTab.value = v
  page.value = 1
  loadList()
}

function changePage(p: number) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  loadList()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function loadList() {
  loading.value = true
  try {
    // 未读走 /unread（最多 50，不分页），其它走 /list 分页
    if (activeTab.value === 0) {
      const res: any = await request.get('/notification/unread')
      items.value = (res.data || []) as NotifyMessage[]
      total.value = items.value.length
    } else {
      const res: any = await request.get('/notification/list', {
        params: { page: page.value, size }
      })
      const pageData = res.data || {}
      let records: NotifyMessage[] = pageData.records || []
      // 按 type 过滤（全部 type=null 不过滤）
      if (activeTab.value !== null) {
        records = records.filter(r => r.type === activeTab.value)
      }
      items.value = records
      total.value = Number(pageData.total) || records.length
    }
  } catch (e: any) {
    console.error('加载通知失败', e)
    ElMessage.error(e?.message || '加载通知失败')
  } finally {
    loading.value = false
  }
}

async function openNotify(n: NotifyMessage) {
  // 先标记已读（不阻塞跳转）
  if (n.isRead === 0 && n.notificationId) {
    try {
      await request.post(`/notification/${n.notificationId}/read`)
      n.isRead = 1
      notifyUnreadCount.value = Math.max(0, notifyUnreadCount.value - 1)
    } catch (e) {
      // 标记失败不影响跳转
    }
  }
  // 跳转
  if (n.articleId) {
    // 有评论定位到评论锚点
    const hash = n.targetId && (n.type === 1 || n.type === 2) ? `#comment-${n.targetId}` : ''
    router.push(`/article/${n.articleId}${hash}`)
  } else if (n.type === 4 && n.targetId) {
    // 关注通知跳对方主页
    router.push(`/user-space/${n.targetId}`)
  }
}

async function markAllRead() {
  try {
    await request.post('/notification/read-all')
    items.value.forEach(n => { n.isRead = 1 })
    notifyUnreadCount.value = 0
    ElMessage.success('已全部标记为已读')
  } catch (e: any) {
    ElMessage.error(e?.message || '操作失败')
  }
}

function goToUserSpace(userId: number | string) {
  if (!userId) return
  router.push(`/user-space/${userId}`)
}

function getAvatarUrl(url?: string | null) {
  if (!url) return 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
  if (url.startsWith('http://') || url.startsWith('https://')) {
    if (url.includes('localhost:8080')) {
      return url.replace(/https?:\/\/localhost:8080/, '')
    }
    return url
  }
  return url
}

function handleAvatarError(e: Event) {
  const t = e.target as HTMLImageElement
  t.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
}

function formatTime(t?: string) {
  if (!t) return ''
  const d = new Date(t.replace(' ', 'T'))
  if (isNaN(d.getTime())) return t
  const diff = Date.now() - d.getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day} 天前`
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${dd}`
}

// 实时推送：进入本页时若有新通知到来，追加到列表顶部（仅"全部"和匹配 type 时）
watch(latestNotify, (msg) => {
  if (!msg) return
  const matchTab =
    activeTab.value === null ||
    activeTab.value === 0 ||  // 未读分类，新消息一定未读
    activeTab.value === msg.type
  if (matchTab && page.value === 1) {
    items.value = [{ ...msg, isRead: 0 }, ...items.value]
    total.value += 1
  }
})

onMounted(() => {
  fetchNotifyUnreadCount()
  loadList()
})

onUnmounted(() => {
  // 离开本页时把本页未读也同步一下（避免其它地方读到过期数据）
  fetchNotifyUnreadCount()
})
</script>

<style scoped>
.notify-page {
  min-height: 100vh;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  position: relative;
}

.notify-page::before {
  content: '';
  position: fixed;
  inset: 0;
  background: #f5f7fa;
  z-index: -2;
}

/* 导航栏 */
.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 70px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 50px;
  z-index: 1000;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 28px;
  font-weight: bold;
  color: #409eff;
  cursor: pointer;
}

.logo-icon {
  width: 32px;
  height: 32px;
}

.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #333;
}

.nav-btn {
  background: transparent;
  color: #666;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 15px;
  transition: all 0.3s;
}

.nav-btn:hover {
  background: #eee;
  color: #409eff;
}

/* 主容器 */
.main {
  max-width: 800px;
  margin: 0 auto;
  padding: 100px 20px 60px;
}

.toolbar {
  background: white;
  border-radius: 16px;
  padding: 14px 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 10px;
}

.tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tab {
  position: relative;
  background: transparent;
  border: none;
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 14px;
  color: #666;
  cursor: pointer;
  transition: all 0.25s;
}

.tab:hover {
  background: #f0f7ff;
  color: #409eff;
}

.tab.active {
  background: #409eff;
  color: white;
  font-weight: 600;
}

.tab-badge {
  margin-left: 5px;
  background: #ff4d4f;
  color: white;
  border-radius: 10px;
  padding: 0 6px;
  font-size: 12px;
  min-width: 18px;
  display: inline-block;
  text-align: center;
}

.tab.active .tab-badge {
  background: white;
  color: #409eff;
}

.btn-mark-all {
  background: white;
  color: #409eff;
  border: 1px solid #409eff;
  padding: 6px 14px;
  border-radius: 18px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s;
}

.btn-mark-all:hover:not(:disabled) {
  background: #409eff;
  color: white;
}

.btn-mark-all:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 列表 */
.list {
  background: white;
  border-radius: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
  overflow: hidden;
}

.notify-card {
  position: relative;
  display: flex;
  gap: 14px;
  padding: 16px 20px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f0;
  transition: background 0.2s;
}

.notify-card:last-child {
  border-bottom: none;
}

.notify-card:hover {
  background: #f8f9fa;
}

.notify-card.unread {
  background: #f0f7ff;
}

.notify-card.unread:hover {
  background: #e6f1ff;
}

.avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid #eee;
  flex-shrink: 0;
  transition: transform 0.2s;
}

.avatar:hover {
  transform: scale(1.05);
  border-color: #409eff;
}

.body {
  flex: 1;
  min-width: 0;
}

.line-1 {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 14px;
  color: #333;
}

.sender {
  font-weight: 600;
  color: #222;
  cursor: pointer;
}

.sender:hover {
  color: #409eff;
}

.verb {
  color: #555;
}

.time {
  margin-left: auto;
  font-size: 12px;
  color: #999;
}

.line-2 {
  margin-top: 6px;
  font-size: 13px;
  color: #666;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.article-title {
  color: #409eff;
}

.target-preview {
  color: #888;
}

.unread-dot {
  position: absolute;
  top: 20px;
  right: 18px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff4d4f;
}

/* 空/Loading */
.state-block {
  background: white;
  border-radius: 16px;
  padding: 60px 20px;
  text-align: center;
  color: #999;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}

.empty .empty-icon svg {
  width: 64px;
  height: 64px;
  color: #ddd;
  margin-bottom: 12px;
}

/* 分页 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
}

.page-btn {
  background: white;
  border: 1px solid #ddd;
  padding: 6px 16px;
  border-radius: 16px;
  cursor: pointer;
  color: #666;
  transition: all 0.25s;
}

.page-btn:hover:not(:disabled) {
  border-color: #409eff;
  color: #409eff;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-info {
  font-size: 14px;
  color: #666;
}

/* 响应式 */
@media (max-width: 768px) {
  .navbar { padding: 0 15px; }
  .page-title { font-size: 16px; }
  .main { padding: 85px 12px 40px; }
  .toolbar { padding: 10px 12px; }
  .notify-card { padding: 12px 14px; }
  .avatar { width: 40px; height: 40px; }
  .unread-dot { top: 16px; right: 14px; }
}
</style>
