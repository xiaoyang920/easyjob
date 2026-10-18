<template>
  <div class="follow-page">
    <!-- 导航栏 -->


    <div class="container">
      <header class="page-header">
        <div>
          <h1>{{ isOwnList ? '我的粉丝与关注' : '粉丝与关注' }}</h1>
          <p class="page-description">{{ isOwnList ? '关注你的人，以及你正在关注的作者。' : '这位作者的粉丝与关注列表。' }}</p>
        </div>
      </header>

      <!-- 标签切换 -->
      <div class="tabs">
        <div 
          :class="['tab-item', { active: currentTab === 'followers' }]"
          @click="switchTab('followers')"
        >
          粉丝 <span class="count">{{ followersCount }}</span>
        </div>
        <div 
          :class="['tab-item', { active: currentTab === 'following' }]"
          @click="switchTab('following')"
        >
          关注 <span class="count">{{ followingCount }}</span>
        </div>
      </div>

      <!-- 用户列表 -->
      <div v-if="loading" class="loading-state">加载中...</div>

      <div v-else-if="userList.length === 0" class="empty-state">
        {{ currentTab === 'followers' ? '暂无粉丝' : '暂无关注' }}
      </div>

      <div v-else class="user-list">
        <div 
          v-for="user in userList" 
          :key="user.userId" 
          class="user-card"
        >
          <img 
            :src="avatarUrl(user.avatar, user.nickName)"
            :alt="`${user.nickName || '用户'}的头像`"
            class="user-avatar"
            @click="goToUserSpace(user.userId)"
            @error="onAvatarError($event, user.nickName)"
          >
          <div class="user-info" @click="goToUserSpace(user.userId)">
            <div class="user-name">{{ user.nickName }}</div>
            <div class="user-intro">{{ user.personIntroduction || '这个人很懒，什么都没有留下~' }}</div>
          </div>
          <button 
            v-if="!isOwner(user.userId)"
            :class="['follow-btn', { following: user.isFollowing }]"
            @click="toggleFollow(user)"
          >
            {{ user.isFollowing ? '已关注' : '关注' }}
          </button>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="userList.length > 0" class="pagination">
        <button 
          class="page-btn" 
          :disabled="currentPage === 1"
          @click="changePage(currentPage - 1)"
        >
          上一页
        </button>
        <span class="page-info">{{ currentPage }} / {{ totalPages || 1 }}</span>
        <button 
          class="page-btn" 
          :disabled="currentPage >= totalPages"
          @click="changePage(currentPage + 1)"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- 登录弹窗 -->
    <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog ej-dialog" append-to-body>
      <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
    </el-dialog>
    <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog ej-dialog" append-to-body>
      <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { goBackOr } from '../utils/navigation'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'
import { avatarUrl, onAvatarError } from '../utils/avatar'

const route = useRoute()
const router = useRouter()

const currentTab = ref('followers')
const userList = ref<any[]>([])
const loading = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)
const followersCount = ref(0)
const followingCount = ref(0)

const userId = ref<string>('')

// 获取URL参数
function getParams() {
  userId.value = route.query.userId as string || localStorage.getItem('userId') || ''
  currentTab.value = route.query.tab as string || 'followers'
}

// 获取用户列表
async function fetchUserList(reset = false) {
  if (reset) {
    currentPage.value = 1
  }

  loading.value = true
  try {
    const url = currentTab.value === 'followers'
      ? `/user/${userId.value}/followers?page=${currentPage.value}&size=10`
      : `/user/${userId.value}/following?page=${currentPage.value}&size=10`

    const res = await request.get(url)
    console.log('用户列表:', res)

    if (res.code === 200 && res.data) {
      userList.value = res.data.records || []
      totalPages.value = res.data.pages || 0

      // 更新计数
      if (currentTab.value === 'followers') {
        followersCount.value = res.data.total || 0
      } else {
        followingCount.value = res.data.total || 0
      }
    }
  } catch (error) {
    console.error('获取用户列表失败:', error)
  } finally {
    loading.value = false
  }
}

// 获取统计数据
async function fetchCounts() {
  try {
    const res = await request.get(`/user/space/${userId.value}`)
    if (res.code === 200 && res.data) {
      followersCount.value = res.data.followerCount || 0
      followingCount.value = res.data.followingCount || 0
    }
  } catch (error) {
    console.error('获取统计失败:', error)
  }
}

// 切换标签
function switchTab(tab: string) {
  currentTab.value = tab
  router.replace({
    query: {
      ...route.query,
      tab: tab
    }
  })
  fetchUserList(true)
}

// 切换页码
function changePage(page: number) {
  currentPage.value = page
  fetchUserList()
  window.scrollTo(0, 0)
}

// 关注/取消关注
async function toggleFollow(user: any) {
  const token = localStorage.getItem('token')
  if (!token) {
    alert('请先登录')
    router.push('/login')
    return
  }

  try {
    const url = user.isFollowing
      ? `/user/${user.userId}/unfollow`
      : `/user/${user.userId}/follow`

    const res = await request.post(url)
    if (res.code === 200) {
      user.isFollowing = !user.isFollowing
    } else {
      alert(res.message || '操作失败')
    }
  } catch (error) {
    console.error('关注操作失败:', error)
  }
}

// 跳转到用户空间
function goToUserSpace(id: string) {
  router.push(`/user-space/${id}`)
}

// 返回进入列表前的页面；切换关注/粉丝标签用的是 replace，不会多出历史记录
function goBack() {
  goBackOr(router, `/user-space/${userId.value}`)
}

// 是否是自己
function isOwner(id: string): boolean {
  return localStorage.getItem('userId') === String(id)
}

// 正在查看自己的列表时，标题和说明用第一人称
const isOwnList = computed(() => isOwner(userId.value))

// 监听路由变化
watch(() => route.query, () => {
  getParams()
  fetchUserList(true)
})

// 登录弹窗状态
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)
const dialogWidth = ref(window.innerWidth <= 480 ? '92%' : '420px')

// 登录过期处理
function handleAuthExpired() {
  showLoginDialog.value = true
}

function handleLoginSuccess() {
  showLoginDialog.value = false
  location.reload()
}

function handleRegisterSuccess() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

function switchToRegister() {
  showLoginDialog.value = false
  showRegisterDialog.value = true
}

function switchToLogin() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

onMounted(() => {
  eventBus.on(EVENT_AUTH_EXPIRED, handleAuthExpired)
  getParams()
  fetchCounts()
  fetchUserList(true)
})

onUnmounted(() => {
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
})
</script>

<style scoped>
.follow-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
}

.follow-page::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--ej-canvas);
  z-index: -2;
}

.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 70px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 50px;
  z-index: 1000;
}

.logo {
  font-size: 28px;
  font-weight: bold;
  color: var(--ej-accent);
  cursor: pointer;
}

.nav-right {
  display: flex;
  gap: 15px;
}

.nav-btn {
  background: transparent;
  color: #666;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.nav-btn:hover {
  background: #eee;
}

.container {
  max-width: 760px;
  margin: 104px auto 50px;
  padding: 0 20px;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h1 {
  font-size: 28px;
}

.page-description {
  margin-top: 8px;
  color: var(--ej-muted);
  font-size: 13px;
  line-height: 1.8;
}

/* 标签与其他列表页一致：左对齐的胶囊，选中为青柠色（配色见 styles/theme.css） */
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 22px;
}

.tab-item {
  padding: 9px 18px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.tab-item .count {
  margin-left: 4px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--ej-muted);
}

.tab-item.active .count {
  color: var(--ej-ink);
}

.loading-state,
.empty-state {
  text-align: center;
  padding: 60px 20px;
  font-size: 15px;
  border-radius: 18px;
  border: 1px dashed var(--ej-line);
}

.user-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 卡片纸面与悬停效果见 styles/theme.css */
.user-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
}

.user-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  object-fit: cover;
  cursor: pointer;
  transition: transform 0.3s;
}

.user-avatar:hover {
  transform: scale(1.05);
}

.user-info {
  flex: 1;
  cursor: pointer;
  overflow: hidden;
}

.user-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--ej-ink);
  margin-bottom: 6px;
}

.user-intro {
  font-size: 13px;
  color: var(--ej-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 配色与已关注状态见 styles/theme.css */
.follow-btn {
  min-width: 88px;
  padding: 8px 20px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

/* 分页 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  margin-top: 30px;
}

.page-btn {
  padding: 10px 24px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 20px;
  color: #666;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.page-btn:hover:not(:disabled) {
  border-color: #333;
  color: #333;
  background: #fafafa;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  color: #666;
  font-size: 14px;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 55px;
  }

  .logo {
    font-size: 20px;
  }

  .nav-btn {
    padding: 6px 12px;
    font-size: 12px;
  }

  .container {
    margin-top: 82px;
    padding: 0 16px;
  }

  .page-header h1 {
    font-size: 24px;
  }

  .card-header h2 {
    font-size: 20px;
  }

  .tab-btn {
    padding: 10px 20px;
    font-size: 14px;
  }

  .user-item {
    padding: 15px 0;
  }

  .user-avatar {
    width: 48px;
    height: 48px;
  }

  .user-name {
    font-size: 15px;
  }

  .follow-btn {
    padding: 6px 18px;
    font-size: 13px;
  }
}

@media (max-width: 480px) {
  .navbar {
    padding: 0 12px;
    height: 50px;
  }

  .logo {
    font-size: 18px;
  }

  .nav-btn {
    padding: 5px 10px;
    font-size: 11px;
  }

  .main-container {
    margin-top: 65px;
    padding: 15px 10px;
  }

  .content-card {
    padding: 15px;
    border-radius: 12px;
  }

  .card-header h2 {
    font-size: 18px;
  }

  .tabs {
    gap: 0;
  }

  .tab-btn {
    padding: 8px 15px;
    font-size: 13px;
    flex: 1;
    text-align: center;
  }

  .user-item {
    padding: 12px 0;
    gap: 12px;
  }

  .user-avatar {
    width: 42px;
    height: 42px;
  }

  .user-name {
    font-size: 14px;
  }

  .user-intro {
    font-size: 12px;
  }

  .follow-btn {
    padding: 5px 14px;
    font-size: 12px;
  }

  .pagination {
    gap: 10px;
  }

  .page-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
}
</style>
