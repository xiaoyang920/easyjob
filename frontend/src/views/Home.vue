<template>
  <div class="home-page">
<!-- 登录弹窗 -->
    <el-dialog
      v-model="showLoginDialog"
      title=""
      :width="dialogWidth"
      :show-close="true"
      destroy-on-close
      class="modern-dialog ej-dialog"
     append-to-body>
      <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
    </el-dialog>

    <!-- 注册弹窗 -->
    <el-dialog
      v-model="showRegisterDialog"
      title=""
      :width="dialogWidth"
      :show-close="true"
      destroy-on-close
      class="modern-dialog ej-dialog"
     append-to-body>
      <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
    </el-dialog>

    <!-- 主容器 -->
    <div class="container">
      <HomeStudio @write="goToCreate" @assistant="goToAiChat" />

      <!-- 分类导航 -->
      <div v-if="categories.length > 0" class="category-nav">
        <button
          class="category-item"
          :class="{ active: selectedCategoryId === null }"
          @click="filterByCategory(null)"
        >
          全部
        </button>
        <button
          v-for="category in categories" 
          :key="category.categoryId"
          class="category-item"
          :class="{ active: selectedCategoryId === category.categoryId }"
          @click="filterByCategory(category.categoryId)"
        >
          {{ category.categoryName }}
        </button>
      </div>
      
      <!-- 主内容区域 -->
      <div class="main-content">
        <!-- 左侧：文章列表 -->
        <div class="articles-section">
          <div class="section-header">
            <h2 class="section-title">精选文章</h2>
            <div class="sort-tabs">
              <button 
                v-for="tab in sortTabs" 
                :key="tab.value"
                class="sort-tab"
                :class="{ active: currentSort === tab.value }"
                @click="changeSortType(tab.value)"
              >
                {{ tab.label }}
              </button>
            </div>
          </div>
          <div class="reading-filter">
            <label><input v-model="readableOnly" type="checkbox" @change="changeReadableFilter">只看可读</label>
            <span>{{ readableOnly ? (isLogin ? '仅展示你现在可以阅读全文的文章' : '仅展示游客可读的文章') : (currentSort === 'recommend' ? '优先推荐可读文章，兼顾关注领域、近期互动与新内容' : '文章卡片会标明阅读等级') }}</span>
            <RouterLink v-if="isLogin && currentSort === 'recommend'" to="/ai-memory">调整关注领域 ↗</RouterLink><button v-if="isLogin && currentSort==='recommend'" class="recommend-preferences" @click="showRecommendationPreferences=true">推荐偏好</button>
          </div>
          <div v-if="loading" class="loading">加载中...</div>
          <div v-else-if="articles.length === 0" class="empty-state">
            <p>{{ readableOnly ? '当前筛选下暂无可读文章' : '暂无文章' }}</p>
            <button v-if="readableOnly" class="sort-tab" @click="readableOnly = false; changeReadableFilter()">查看全部文章</button>
          </div>
          <div v-else class="article-grid">
            <div 
              v-for="(article, articleIndex) in articles"
              :key="article.articleId || article.id"
              class="article-card"
              :class="{ 'is-menu-open': feedbackMenuId === String(article.articleId || article.id) }"
              tabindex="0"
              role="link"
              @keydown.enter="viewArticle(article.articleId || article.id)"
              @click="viewArticle(article.articleId || article.id)"
            >
              <div class="cover-wrapper">
                <img 
                  v-if="getImageUrl(article.coverImage || article.cover) && getImageUrl(article.coverImage || article.cover) !== '/images/default-cover.jpg'"
                  v-lazyload="{
                    src: getThumbUrl(getImageUrl(article.coverImage || article.cover)) || getImageUrl(article.coverImage || article.cover),
                    fallback: getImageUrl(article.coverImage || article.cover)
                  }"
                  :alt="article.title" 
                  class="article-cover"
                  @error="handleCoverError($event, article.coverImage || article.cover)"
                >
                <CoverPlaceholder v-else class="no-cover-placeholder" :title="stripHtmlTags(article.title)" :label="categoryLabel(article)" />
              </div>

              <div class="article-info">
                <div class="studio-card-index">
                  <span class="card-kicker"><span class="card-dot" aria-hidden="true"></span><span class="card-number">{{ String(articleIndex + 1).padStart(2, '0') }}</span><span class="card-kicker-text">{{ cardKicker(article) }}</span></span>
                  <span class="card-actions">
                    <span v-if="isLogin && currentSort === 'recommend'" class="card-menu" @click.stop @keydown.stop>
                      <el-dropdown trigger="click" @command="(kind: string) => recommendationFeedback(article.articleId || article.id, kind)" @visible-change="(open: boolean) => { feedbackMenuId = open ? String(article.articleId || article.id) : '' }">
                        <button type="button" class="card-more" :disabled="!!feedbackBusy" :aria-label="`调整《${article.title}》的推荐`">⋯</button>
                        <template #dropdown><el-dropdown-menu><el-dropdown-item command="not_interested">不感兴趣</el-dropdown-item><el-dropdown-item command="hide_author">不再推荐该作者</el-dropdown-item></el-dropdown-menu></template>
                      </el-dropdown>
                    </span>
                    <span class="card-arrow" aria-hidden="true">↗</span>
                  </span>
                </div>
                <span v-if="article.requiredLevel > 0" class="reading-level-badge">{{ article.readableNow === false ? `需 L${article.requiredLevel} 解锁` : `L${article.requiredLevel} · 可读` }}</span>
                <div class="article-title">{{ article.title }}</div>
                <p v-if="article.summary" class="article-deck">{{ stripHtmlTags(article.summary) }}</p>
                <div class="article-byline">
                  <span class="byline-author"><img :src="avatarUrl(article.authorAvatar, cardAuthor(article))" alt="" class="byline-avatar" @error="onAvatarError($event, cardAuthor(article))">{{ cardAuthor(article) }}</span>
                  <span>{{ formatNumber(article.viewCount || 0) }} 次阅读</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 分页 -->
          <div v-if="totalPages > 0" class="pagination">
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

        <!-- 右侧：功能卡片 -->
        <div class="sidebar">
          <div class="features">
            <div class="feature-card" @click="goToCreate">
              <div class="feature-icon">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                </svg>
              </div>
              <div class="feature-title">创作文章</div>
              <div class="feature-desc">把实践和新想法，写成下一篇文章。</div>
            </div>
            <div class="feature-card" @click="goToSpace">
              <div class="feature-icon">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
                </svg>
              </div>
              <div class="feature-title">个人空间</div>
              <div class="feature-desc">管理你的文章、草稿，查看粉丝和关注</div>
            </div>
            <div class="feature-card" @click="goToDrafts">
              <div class="feature-icon">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>
                </svg>
              </div>
              <div class="feature-title">草稿箱</div>
              <div class="feature-desc">保存未完成的文章，随时继续创作</div>
            </div>
            <div class="feature-card ai-card" @click="goToAiChat">
              <div class="feature-icon">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="m14 4 6 6-9 9-7 1 1-7 9-9Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="m12 6 6 6M5 19l4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              </div>
              <div class="feature-title">AI 助手</div>
              <div class="feature-desc">写作灵感，文章优化，内容润色</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <RecommendationPreferences v-model="showRecommendationPreferences" @changed="loadArticles" />
</template>

<script setup lang="ts">
import RecommendationPreferences from '@/components/RecommendationPreferences.vue'
import { clearAccountStorage } from '@/utils/searchHistory'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import LoginForm from '@/components/LoginForm.vue'
import RegisterForm from '@/components/RegisterForm.vue'
import HomeStudio from '@/components/HomeStudio.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import request from '@/utils/request'
import { getThumbUrl, onThumbError } from '@/utils/image'
import { avatarUrl, onAvatarError } from '@/utils/avatar'
import { eventBus, EVENT_AUTH_EXPIRED, EVENT_AUTH_CHANGED } from '@/utils/eventBus'
import {
  notifyUnreadCount,
  connectNotifyStream,
  closeNotifyStream,
  fetchNotifyUnreadCount,
  resetNotifyState,
  latestNotify
} from '@/utils/notification'
import { watch } from 'vue'

const router = useRouter()
const route = useRoute()

// 弹窗状态
const showLoginDialog = ref(false)
const showRegisterDialog = ref(false)
const redirectPath = ref('')

// 响应式弹窗宽度
const dialogWidth = ref('420px')

// 检测屏幕宽度并设置弹窗宽度
function updateDialogWidth() {
  if (window.innerWidth <= 480) {
    dialogWidth.value = '90%'
  } else {
    dialogWidth.value = '420px'
  }
}

// 组件卸载时清理定时器和事件监听
onUnmounted(() => {
  // 清理未读消息轮询定时器
  if (unreadTimer) {
    clearInterval(unreadTimer)
    unreadTimer = null
  }
  // 断开通知 SSE
  closeNotifyStream()
  // 移除登录过期事件监听
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
  eventBus.off(EVENT_AUTH_CHANGED, init)
  window.removeEventListener('resize', updateDialogWidth)
})

// 状态
const loading = ref(false)
const articles = ref<any[]>([])
const currentSort = ref('recommend')
const showRecommendationPreferences=ref(false),feedbackBusy=ref('')
// 正在展开“调整推荐”菜单的卡片，菜单打开期间保持更多按钮可见
const feedbackMenuId = ref('')
async function recommendationFeedback(id:string,kind:string){if(feedbackBusy.value)return;feedbackBusy.value=id;try{await request.put(`/recommendation/feedback/${id}`,{kind});ElMessage.success('推荐偏好已更新');await loadArticles()}catch(e){ElMessage.error(e instanceof Error?e.message:'反馈失败，请重试')}finally{feedbackBusy.value=''}}
const readableOnly = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)
const isLogin = ref(false)
const nickName = ref('用户')
const avatar = ref('')
const searchKeyword = ref('')
const userStats = ref({
  followingCount: 0,
  followerCount: 0,
  articleCount: 0
})

// 未读消息总数
const totalUnreadCount = ref(0)
let unreadTimer: number | null = null
let isLoadingUnread = false  // 防抖标记

// 分类和标签
const categories = ref<any[]>([])
const selectedCategoryId = ref<number | null>(null)
const selectedTagIds = ref<number[]>([])

// 分类 id → 名称（含二级分类），用于卡片眉题和无封面占位
const categoryNames = computed(() => {
  const names = new Map<string, string>()
  for (const category of categories.value) {
    names.set(String(category.categoryId), category.categoryName)
    for (const child of category.children || []) names.set(String(child.categoryId), child.categoryName)
  }
  return names
})

function categoryLabel(article: any): string {
  return article.categoryId ? categoryNames.value.get(String(article.categoryId)) || '' : ''
}

// 卡片眉题：推荐流显示推荐理由，其他排序显示分类
function cardKicker(article: any): string {
  if (currentSort.value === 'recommend' && article.recommendationReason) return article.recommendationReason
  return categoryLabel(article) || '文章'
}

function cardAuthor(article: any): string {
  return article.authorName || article.nickName || '社区创作者'
}

// 搜索处理
function handleSearch() {
  if (!searchKeyword.value.trim()) return
  router.push(`/search?keyword=${encodeURIComponent(searchKeyword.value.trim())}`)
}

// 排序选项
const sortTabs = [
  { label: '推荐', value: 'recommend' },
  { label: '最新发布', value: 'latest' },
  { label: '最热门', value: 'hottest' },
  { label: '点赞最多', value: 'liked' }
]

// 处理图片URL，如果是相对路径则添加后端地址
function getImageUrl(url: string | undefined): string {
  if (!url) {
    console.log('封面URL为空，使用默认封面')
    return '/images/default-cover.jpg'
  }
  
  // 如果是完整URL（http/https开头）
  if (url.startsWith('http://') || url.startsWith('https://')) {
    // 如果是localhost的URL，去掉域名部分，只保留路径
    if (url.includes('localhost:8080')) {
      const path = url.replace(/https?:\/\/localhost:8080/, '')
      console.log('转换localhost URL:', url, '=>', path)
      return path
    }
    console.log('封面是完整URL:', url)
    return url
  }
  
  // 如果是相对路径（/uploads开头），直接返回
  if (url.startsWith('/uploads')) {
    console.log('封面转换: ', url)
    return url
  }
  
  console.log('封面URL其他情况:', url)
  return url
}

// 初始化
function init() {
  const token = localStorage.getItem('token')
  const storedNickName = localStorage.getItem('nickName')
  const storedAvatar = localStorage.getItem('avatar')
  
  isLogin.value = !!token
  
  if (isLogin.value) {
    nickName.value = storedNickName || '用户'
    avatar.value = storedAvatar || ''
  } else {
    nickName.value = '用户'
    avatar.value = ''
    totalUnreadCount.value = 0
    if (unreadTimer) {
      clearInterval(unreadTimer)
      unreadTimer = null
    }
  }
}

// 401登录过期处理回调
function handleAuthExpired() {
  isLogin.value = false
  nickName.value = '用户'
  avatar.value = ''
  totalUnreadCount.value = 0
  if (unreadTimer) {
    clearInterval(unreadTimer)
    unreadTimer = null
  }
  // 断开通知 SSE，清空通知状态
  closeNotifyStream()
  resetNotifyState()
  showLoginDialog.value = true
}

onMounted(() => {
  init()
  // 监听登录过期事件
  eventBus.on(EVENT_AUTH_EXPIRED, handleAuthExpired)
  eventBus.on(EVENT_AUTH_CHANGED, init)
  loadCategories()  // 获取分类列表
  loadArticles()
  if (isLogin.value) {
    loadUserInfo()
    loadUnreadCount()
    // 定时轮询未读消息数（每60秒）
    unreadTimer = window.setInterval(() => {
      if (isLogin.value) {
        loadUnreadCount()
      }
    }, 60000)
    // 通知：拉未读数 + 建立 SSE
    fetchNotifyUnreadCount()
    connectNotifyStream()
  }
  
  // 检查是否需要显示登录弹窗（从需要登录的页面跳转过来）
  if (route.query.login === 'true') {
    showLoginDialog.value = true
    redirectPath.value = (route.query.redirect as string) || ''
    // 清除 URL 中的查询参数
    router.replace({ path: '/', query: {} })
  }
  
  // 检查是否需要显示注册弹窗
  if (route.query.register === 'true') {
    showRegisterDialog.value = true
    redirectPath.value = (route.query.redirect as string) || ''
    router.replace({ path: '/', query: {} })
  }
  
  // 初始化和监听窗口大小变化
  updateDialogWidth()
  window.addEventListener('resize', updateDialogWidth)
})

// Ignore results from an obsolete sort/category request.
let articleLoadSequence = 0
async function loadArticles() {
  const sequence = ++articleLoadSequence
  loading.value = true
  const params: any = { page: currentPage.value, size: 12, sort: currentSort.value, readableOnly: readableOnly.value }
  if (selectedCategoryId.value) params.categoryId = selectedCategoryId.value
  if (selectedTagIds.value.length) params.tagIds = selectedTagIds.value.join(',')
  try {
    const response = await request.get(currentSort.value === 'recommend' ? '/article/recommend' : '/article/list', { params })
    if (sequence !== articleLoadSequence) return
    if (response.status === 'success' && response.data) {
      articles.value = response.data.records || []
      totalPages.value = response.data.pages || 1
    }
  } catch (error) {
    if (sequence === articleLoadSequence) { articles.value = []; totalPages.value = 1; console.error('加载文章失败:', error) }
  } finally {
    if (sequence === articleLoadSequence) loading.value = false
  }
}

function changeReadableFilter() {
  currentPage.value = 1
  loadArticles()
}

// 加载未读消息总数（带防抖）
async function loadUnreadCount() {
  if (isLoadingUnread) return  // 防止重复请求
  isLoadingUnread = true
  try {
    const response = await request.get('/chat/total-unread-count')
    if (response.code === 200) {
      totalUnreadCount.value = response.data || 0
    }
  } catch (error) {
    console.error('加载未读消息数失败:', error)
  } finally {
    isLoadingUnread = false
  }
}

// 加载用户信息
async function loadUserInfo() {
  try {
    const userId = localStorage.getItem('userId')
    if (!userId) return
    
    const response = await request.get(`/user/space/${userId}`)
    
    if (response.code === 200 && response.data) {
      nickName.value = response.data.nickName || '用户'
      localStorage.setItem('nickName', response.data.nickName || '用户')
      
      if (response.data.avatar) {
        avatar.value = response.data.avatar
        localStorage.setItem('avatar', response.data.avatar)
      }
      
      // 更新统计数据
      userStats.value = {
        followingCount: response.data.followingCount || 0,
        followerCount: response.data.followerCount || 0,
        articleCount: response.data.articleCount || 0
      }
    }
  } catch (error) {
    console.error('加载用户信息失败:', error)
  }
}

// 获取分类列表
async function loadCategories() {
  try {
    const response = await request.get('/category/list')
    if (response.code === 200) {
      categories.value = response.data || []
    }
  } catch (error) {
    console.error('获取分类失败:', error)
  }
}

// 按分类筛选
function filterByCategory(categoryId: number | null) {
  selectedCategoryId.value = categoryId
  currentPage.value = 1
  loadArticles()
}

// 按标签筛选
function filterByTag(tagId: number) {
  // 切换标签选中状态
  const index = selectedTagIds.value.indexOf(tagId)
  if (index > -1) {
    selectedTagIds.value.splice(index, 1)
  } else {
    selectedTagIds.value.push(tagId)
  }
  currentPage.value = 1
  loadArticles()
}

// 切换排序
function changeSortType(sort: string) {
  currentSort.value = sort
  currentPage.value = 1
  loadArticles()
}

// 切换页码
function changePage(page: number) {
  currentPage.value = page
  loadArticles()
  window.scrollTo({ top: 400, behavior: 'smooth' })
}

// 查看文章
function viewArticle(articleId: string) {
  // 移动端在当前页面打开，电脑端新开页面
  if (window.innerWidth <= 768) {
    router.push(`/article/${articleId}`)
  } else {
    window.open(`/article/${articleId}`, '_blank')
  }
}

// 格式化数字
function formatNumber(num: number) {
  if (num >= 10000) {
    return (num / 10000).toFixed(1) + '万'
  }
  return num
}

// 导航函数
function goToCreate() {
  if (!isLogin.value) {
    redirectPath.value = '/create-article?new=true'
    showLoginDialog.value = true
    return
  }
  router.push('/create-article?new=true')
}

function goToSpace() {
  if (!isLogin.value) {
    redirectPath.value = '/user-space'
    showLoginDialog.value = true
    return
  }
  router.push('/user-space')
}

function goToDrafts() {
  if (!isLogin.value) {
    redirectPath.value = '/draft-box'
    showLoginDialog.value = true
    return
  }
  router.push('/draft-box')
}

function goToChat() {
  if (!isLogin.value) {
    redirectPath.value = '/chat'
    showLoginDialog.value = true
    return
  }
  router.push('/chat')
}

// 跳转到通知页
function goToNotifications() {
  if (!isLogin.value) {
    redirectPath.value = '/notifications'
    showLoginDialog.value = true
    return
  }
  router.push('/notifications')
}

// 新通知到达时弹 toast（不在通知页时才提示）
watch(latestNotify, (msg) => {
  if (!msg) return
  if (route.path === '/notifications') return
  ElMessage({
    message: `${msg.senderNickname || '有人'} ${msg.content}`,
    type: 'info',
    duration: 3000,
    showClose: true
  })
})

// 跳转到 AI 助手
function goToAiChat() {
  if (!isLogin.value) {
    redirectPath.value = '/ai-chat'
    showLoginDialog.value = true
    return
  }
  router.push('/ai-chat')
}

// 跳转到粉丝页
function goToFollowers() {
  const userId = localStorage.getItem('userId')
  router.push(`/followers-following?userId=${userId}&tab=followers`)
}

// 跳转到关注页
function goToFollowing() {
  const userId = localStorage.getItem('userId')
  router.push(`/followers-following?userId=${userId}&tab=following`)
}

// 退出登录
function logout() {
  clearAccountStorage()
  isLogin.value = false
  nickName.value = '用户'
  avatar.value = ''
  totalUnreadCount.value = 0
  // 清除轮询定时器
  if (unreadTimer) {
    clearInterval(unreadTimer)
    unreadTimer = null
  }
  // 断开通知 SSE，清空通知状态
  closeNotifyStream()
  resetNotifyState()
  ElMessage.success('已退出登录')
  loadArticles()
}

// 登录成功处理
function handleLoginSuccess(message = '登录成功') {
  showLoginDialog.value = false
  init()
  loadArticles()
  if (isLogin.value) {
    loadUserInfo()
    loadUnreadCount()
    // 启动定时轮询
    if (!unreadTimer) {
      unreadTimer = window.setInterval(() => {
        if (isLogin.value) {
          loadUnreadCount()
        }
      }, 60000)
    }
    // 通知：拉未读数 + 建立 SSE
    fetchNotifyUnreadCount()
    connectNotifyStream()
  }
  ElMessage.success(message)
  
  // 如果有重定向路径，跳转到目标页面
  if (redirectPath.value) {
    const path = redirectPath.value
    redirectPath.value = ''
    router.push(path)
  }
}

// 注册成功处理
function handleRegisterSuccess() {
  showRegisterDialog.value = false
  handleLoginSuccess('注册成功，已自动登录')
}

// 切换到注册
function switchToRegister() {
  showLoginDialog.value = false
  showRegisterDialog.value = true
}

// 切换到登录
function switchToLogin() {
  showRegisterDialog.value = false
  showLoginDialog.value = true
}

function handleCoverError(e: Event, originalCover?: string) {
  const target = e.target as HTMLImageElement
  const currentSrc = target.src
  
  // 缩略图加载失败，回退到原图
  if (currentSrc.includes('/thumbnails/') && originalCover) {
    target.src = getImageUrl(originalCover)
    return
  }
  
  // 原图也加载失败，显示默认封面
  target.src = 'data:image/svg+xml,%3Csvg width="300" height="180" xmlns="http://www.w3.org/2000/svg"%3E%3Crect width="300" height="180" fill="%23f0f2f5"/%3E%3Ctext x="150" y="90" font-family="Arial" font-size="24" fill="%23999" text-anchor="middle" dominant-baseline="middle"%3EEasyJob%3C/text%3E%3Ctext x="150" y="120" font-family="Arial" font-size="14" fill="%23ccc" text-anchor="middle" dominant-baseline="middle"%3E默认封面%3C/text%3E%3C/svg%3E'
}

// 去除HTML标签
function stripHtmlTags(str: string): string {
  if (!str) return ''
  return str.replace(/<[^>]*>/g, '')
}

</script>

<style scoped>
.recommend-preferences{font:inherit;font-size:12px;border:0;background:transparent;color:var(--ej-ink);cursor:pointer}.recommend-preferences:hover{text-decoration:underline}

/* 复选框样式见 styles/theme.css 的表单控件部分 */
.reading-filter { display:flex; align-items:center; flex-wrap:wrap; gap:10px 18px; margin:0 0 24px; font-size:12px; color:var(--ej-muted); }
.reading-filter label { display:flex; align-items:center; gap:8px; color:var(--ej-ink); cursor:pointer; white-space:nowrap; }
.reading-filter a { color:#4e5d35; text-decoration:none; margin-left:auto; }
.home-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
  overflow-x: hidden;
}

.home-page::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--ej-canvas);
  z-index: -2;
  will-change: transform;
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
  justify-content: space-between;
  align-items: center;
  padding: 0 50px;
  z-index: 1000;
  transform: translateZ(0);
  backface-visibility: hidden;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 28px;
  font-weight: bold;
  color: var(--ej-accent);
  cursor: pointer;
  transition: all 0.3s;
}

.logo-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.logo-text {
  display: inline;
}

.logo:hover {
  transform: scale(1.05);
}

/* 搜索框 */
.search-box {
  flex: 1;
  max-width: 400px;
  margin: 0 40px;
  position: relative;
}

.search-box input {
  width: 100%;
  height: 40px;
  padding: 0 45px 0 18px;
  border: 1px solid #ddd;
  border-radius: 20px;
  font-size: 14px;
  outline: none;
  transition: all 0.3s;
  background: white;
  color: #333;
}

.search-box input::placeholder {
  color: #999;
}

/* 隐藏原生搜索清除按钮 */
.search-box input[type="search"]::-webkit-search-cancel-button {
  -webkit-appearance: none;
  display: none;
}

.search-box input:focus {
  border-color: var(--ej-accent);
  background: white;
}

.search-btn {
  position: absolute;
  right: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  background: var(--ej-accent);
  border: none;
  border-radius: 50%;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.search-btn:hover {
  background: var(--ej-ink);
}

.nav-menu {
  display: flex;
  gap: 20px;
  align-items: center;
}

/* 导航图标按钮 */
.nav-icon-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 8px;
  transition: all 0.3s;
  color: #666;
}

.nav-icon-btn:hover {
  background: #eee;
  color: var(--ej-accent);
}

.nav-icon-btn svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}

.nav-icon-btn span {
  font-size: 12px;
}

/* AI 助手按钮特殊样式 */
.nav-icon-btn.ai-btn {
  color: #666;
}

.nav-icon-btn.ai-btn:hover {
  background: var(--ej-accent-soft);
  color: var(--ej-accent);
}

/* 消息角标 */
.msg-badge {
  display: flex;
}

.msg-badge :deep(.el-badge__content) {
  top: 4px;
  right: 14px;
  transform: translateY(-50%) translateX(50%);
}

.nav-btn {
  background: transparent;
  color: #666;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.3s;
}

.nav-btn:hover {
  background: #eee;
  transform: translateY(-2px);
}

.nav-btn.primary {
  background: var(--ej-accent);
  color: white;
  font-weight: 600;
}

.nav-btn.primary:hover {
  background: var(--ej-ink);
  box-shadow: 0 4px 12px rgba(17, 17, 15, 0.3);
}

.user-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid #ddd;
  cursor: pointer;
  transition: all 0.3s;
  object-fit: cover;
  display: block;
}

.user-avatar:hover {
  border-color: var(--ej-accent);
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(17, 17, 15, 0.2);
}

/* 用户下拉菜单 */
.user-dropdown {
  position: relative;
  margin-left: 10px;
}

.dropdown-trigger {
  cursor: pointer;
  position: relative;
  z-index: 1002;
}

.dropdown-trigger .user-avatar {
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.user-dropdown:hover .dropdown-trigger .user-avatar {
  transform: scale(2);
  border-color: white;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.dropdown-menu {
  position: absolute;
  top: 25px;
  left: 50%;
  transform: translateX(-50%) translateY(10px);
  width: 300px;
  padding-top: 45px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.18);
  opacity: 0;
  visibility: hidden;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 1001;
  overflow: hidden;
}

.user-dropdown:hover .dropdown-menu {
  opacity: 1;
  visibility: visible;
  transform: translateX(-50%) translateY(0);
}

/* 头像区域占位 - 头像嵌入卡片顶部 */
.dropdown-avatar-wrapper {
  display: none;
}

/* 下拉菜单主体 */
.dropdown-body {
  border-radius: 16px;
  overflow: hidden;
}

.dropdown-user-name {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  text-align: center;
  padding: 15px 20px 15px;
}

.dropdown-stats {
  display: flex;
  justify-content: space-around;
  padding: 15px 20px;
  background: #f8f9fa;
  border-top: 1px solid #f0f0f0;
  border-bottom: 1px solid #f0f0f0;
}

.dropdown-stats .stat-item {
  text-align: center;
  cursor: pointer;
  padding: 8px 20px;
  border-radius: 10px;
  transition: all 0.25s;
}

.dropdown-stats .stat-item:hover {
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.dropdown-stats .stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #333;
}

.dropdown-stats .stat-label {
  font-size: 12px;
  color: #999;
  margin-top: 3px;
}

.dropdown-items {
  padding: 10px 0;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 20px;
  color: #333;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.dropdown-item:hover {
  background: #f5f5f5;
}

.dropdown-item svg {
  width: 20px;
  height: 20px;
  fill: #666;
  flex-shrink: 0;
}

.dropdown-item span {
  flex: 1;
}

.dropdown-item svg.arrow {
  width: 18px;
  height: 18px;
  fill: #ccc;
}

.dropdown-footer {
  border-top: 1px solid #f0f0f0;
  padding: 10px 0;
}

.dropdown-item.logout {
  color: #ff4d4f;
}

.dropdown-item.logout svg {
  fill: #ff4d4f;
}

.dropdown-item.logout:hover {
  background: #fff2f0;
}

/* 下拉菜单中的未读消息badge */
.dropdown-badge {
  background: #ff4d4f;
  color: white;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}

/* AI助手菜单项 */
.dropdown-item.ai-item svg {
  fill: var(--ej-accent);
}

.dropdown-item.ai-item:hover {
  background: linear-gradient(135deg, rgba(17, 17, 15, 0.1), rgba(17, 17, 15, 0.1));
}

/* 主容器 */
.container {
  position: relative;
  z-index: 1;
  max-width: 1400px;
  margin: 100px auto 50px;
  padding: 0 20px;
}

/* 分类导航 */
.category-nav {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  padding: 10px 14px;
  background: white;
  border: 1px solid #edf0f3;
  border-radius: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: thin;
}

.category-nav::-webkit-scrollbar {
  height: 6px;
}

.category-nav::-webkit-scrollbar-thumb {
  background: #e0e0e0;
  border-radius: 3px;
}

.category-item {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
  color: #6b7280;
  background: transparent;
  flex-shrink: 0;
}

.category-item:hover {
  background: #f4f6fa;
  color: #1f2937;
}

.category-item.active {
  background: #1f2937;
  color: white;
  font-weight: 500;
}

.welcome-section {
  text-align: center;
  margin-bottom: 40px;
  animation: fadeIn 1s ease-out;
}

.welcome-title {
  font-size: 36px;
  color: #1f2937;
  margin-bottom: 12px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.welcome-subtitle {
  font-size: 15px;
  color: #6b7280;
  letter-spacing: 0.01em;
}

/* 移动端登录提示 - 默认隐藏 */
.mobile-login-tip {
  display: none;
  font-size: 13px;
  color: #999;
  margin-top: 12px;
  padding: 8px 16px;
  background: rgba(17, 17, 15, 0.08);
  border-radius: 20px;
  width: fit-content;
  margin-left: auto;
  margin-right: auto;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.main-content {
  display: flex;
  gap: 30px;
  align-items: flex-start;
}

.articles-section {
  flex: 1;
  background: white;
  border: 1px solid #edf0f3;
  border-radius: 16px;
  padding: 32px 32px 28px;
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.04);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.section-title {
  font-size: 22px;
  font-weight: 600;
  color: #1f2937;
  letter-spacing: -0.01em;
  margin: 0;
}

.sort-tabs {
  display: flex;
  gap: 4px;
  background: #f4f6fa;
  padding: 4px;
  border-radius: 10px;
}

.sort-tab {
  padding: 6px 14px;
  border: none;
  background: transparent;
  color: #6b7280;
  font-size: 13px;
  cursor: pointer;
  border-radius: 7px;
  transition: color 0.2s ease, background 0.2s ease;
  white-space: nowrap;
}

.sort-tab:hover {
  color: #1f2937;
}

.sort-tab.active {
  background: white;
  color: #1f2937;
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.article-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.article-card {
  background: white;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  will-change: transform;
}

.article-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
}

.article-card:hover .article-cover {
  transform: scale(1.05);
}

.article-cover {
  width: 100%;
  height: 180px;
  object-fit: cover;
  background: #e8e8e8;
  display: block;
  transform: translateZ(0);
  backface-visibility: hidden;
  position: absolute;
  top: 0;
  left: 0;
  transition: opacity 0.3s ease-in-out, transform 0.3s ease;
}

/* 懒加载状态样式 */
.article-cover.lazy-loading {
  opacity: 0;
}

.article-cover.lazy-loaded {
  opacity: 1;
}

.article-cover.lazy-error {
  opacity: 0.5;
}

/* 无封面占位见 components/CoverPlaceholder.vue，卡片配色见 styles/home-studio.css */
.cover-wrapper {
  width: 100%;
  height: 180px;
  overflow: hidden;
  position: relative;
}

.article-info {
  padding: 12px;
}

.article-title {
  font-size: 14px;
  font-weight: 500;
  color: #18191c;
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.4;
  min-height: 40px;
}

/* 作者信息 */
.article-author {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #999;
}

.author-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 文章标签 */
.article-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.category-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  background: #ecf5ff;
  color: var(--ej-accent);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.tag-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  background: #f4f6fa;
  color: #6b7280;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.tag-badge:hover {
  background: #ecf5ff;
  color: var(--ej-accent);
}

.article-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 14px;
  color: #999;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.sidebar {
  width: 320px;
  flex-shrink: 0;
}

.features {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.feature-card {
  background: white;
  border: 1px solid #edf0f3;
  border-radius: 14px;
  padding: 18px 20px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  will-change: transform;
}

.feature-card:hover {
  transform: translateY(-2px);
  border-color: var(--ej-ink);
  box-shadow: 0 8px 24px rgba(17, 17, 15, 0.1);
}

/* AI 助手卡片特殊样式 */
.feature-card.ai-card .feature-icon {
  color: var(--ej-accent);
}

.feature-card.ai-card:hover {
  border-color: var(--ej-ink);
}

.feature-icon {
  width: 28px;
  height: 28px;
  margin: 0 0 10px 0;
  color: #6b7280;
  display: flex;
  align-items: center;
  justify-content: center;
}

.feature-icon svg {
  width: 100%;
  height: 100%;
}

.feature-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 4px;
  letter-spacing: -0.01em;
}

.feature-desc {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.55;
}

.loading {
  text-align: center;
  padding: 40px;
  color: var(--ej-accent);
  font-size: 16px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
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
  background: #f7f9fc;
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
  background: #f0f0f0;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  color: #666;
  font-size: 14px;
}

@media (max-width: 1200px) {
  .main-content {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
  }
}

/* 平板适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 60px;
  }
  
  .logo {
    font-size: 20px;
  }
  
  .search-box {
    margin: 0 10px;
    max-width: none;
    flex: 1;
  }
  
  .search-box input {
    height: 36px;
    font-size: 13px;
  }
  
  .nav-menu {
    gap: 5px;
  }
  
  .nav-icon-btn {
    padding: 8px;
  }
  
  .nav-icon-btn span {
    display: none;
  }
  
  .nav-icon-btn svg {
    width: 20px;
    height: 20px;
  }
  
  .container {
    padding: 0 15px;
  }
  
  .welcome-section {
    margin-top: 80px;
    padding: 20px 0;
  }
  
  .welcome-title {
    font-size: 24px !important;
  }
  
  .welcome-subtitle {
    font-size: 14px !important;
  }
  
  .main-content {
    margin-top: 20px;
    padding: 0;
    flex-direction: column;
    align-items: center;
  }
  
  .articles-section {
    padding: 20px;
    border-radius: 15px;
    width: 100%;
    max-width: 500px;
  }
  
  .section-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 15px;
  }
  
  .section-title {
    font-size: 20px;
  }
  
  .section-icon {
    width: 22px;
    height: 22px;
  }
  
  .sort-tabs {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  
  .sort-tab {
    padding: 8px 16px;
    font-size: 13px;
  }
  
  .article-grid {
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 15px;
  }
  
  .cover-wrapper {
    height: 160px;
  }
  
  .article-cover {
    height: 160px;
  }
  
  .no-cover-placeholder {
    height: 160px;
  }
  
  .article-info {
    padding: 10px;
  }
  
  .article-title {
    font-size: 14px;
    min-height: 40px;
  }
  
  .sidebar {
    display: none;
  }
  
  /* 下拉菜单 */
  .dropdown-menu {
    right: -20px;
    width: 280px;
  }
}

/* 手机适配 */
@media (max-width: 480px) {
  .navbar {
    padding: 0 10px;
    height: 55px;
  }
  
  .logo {
    font-size: 18px;
  }
  
  .logo-icon {
    width: 28px;
    height: 28px;
  }
  
  .logo-text {
    display: none;
  }
  
  .search-box {
    margin: 0 8px;
  }
  
  /* 移动端隐藏导航栏功能按钮，只保留头像 */
  .nav-icon-btn {
    display: none;
  }
  
  .msg-badge {
    display: none;
  }
  
  .search-box input {
    height: 32px;
    padding: 0 36px 0 12px;
    font-size: 12px;
  }
  
  .search-btn {
    width: 28px;
    height: 28px;
    right: 2px;
  }
  
  .search-btn svg {
    width: 14px;
    height: 14px;
  }
  
  .user-avatar {
    width: 30px;
    height: 30px;
  }
  
  .nav-icon-btn {
    padding: 6px;
  }
  
  .nav-icon-btn svg {
    width: 18px;
    height: 18px;
  }
  
  .container {
    padding: 0 10px;
  }
  
  .welcome-section {
    margin-top: 70px;
    padding: 15px 0;
  }
  
  .welcome-title {
    font-size: 20px !important;
  }
  
  .welcome-subtitle {
    font-size: 13px !important;
  }
  
  /* 移动端显示登录提示 */
  .mobile-login-tip {
    display: block;
  }
  
  .main-content {
    margin-top: 15px;
    flex-direction: column;
    align-items: center;
  }
  
  .articles-section {
    padding: 15px;
    border-radius: 12px;
    width: 100%;
    max-width: 100%;
  }
  
  .section-header {
    margin-bottom: 20px;
  }
  
  .section-title {
    font-size: 18px;
  }
  
  .section-icon {
    width: 20px;
    height: 20px;
  }
  
  .sort-tabs {
    gap: 5px;
    padding: 4px;
  }
  
  .sort-tab {
    padding: 6px 12px;
    font-size: 12px;
    border-radius: 6px;
  }
  
  .article-grid {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
  }
  
  .article-card {
    border-radius: 10px;
  }
  
  .cover-wrapper {
    height: 140px;
    border-radius: 10px 10px 0 0;
  }
  
  .article-cover {
    height: 140px;
  }
  
  .no-cover-placeholder {
    height: 140px;
  }
  
  .article-info {
    padding: 8px;
  }
  
  .article-title {
    font-size: 13px;
    min-height: 36px;
    margin-bottom: 0;
  }
  
  .article-meta {
    gap: 8px;
    font-size: 12px;
  }
  
  .article-stats {
    gap: 12px;
  }
  
  .article-stats span {
    font-size: 12px;
  }
  
  .sidebar {
    display: none;
  }
  
  /* 下拉菜单 - 移动端往左展开 */
  .dropdown-menu {
    right: 0;
    left: auto;
    width: 260px;
    transform: translateX(0) translateY(10px);
  }
  
  .user-dropdown:hover .dropdown-menu {
    transform: translateX(0) translateY(0);
  }
  
  .dropdown-item {
    padding: 12px 16px;
    font-size: 14px;
  }
  
  /* 分页 */
  .pagination-wrapper {
    padding: 15px 0;
  }
}
</style>

<!-- 全局样式用于弹窗 -->
<style>
.modern-dialog .el-dialog {
  border-radius: 15px;
  overflow: hidden;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
}

.modern-dialog .el-dialog__header {
  padding: 0;
  margin: 0;
  height: 0;
}

.modern-dialog .el-dialog__body {
  padding: 0;
}

.modern-dialog .el-dialog__headerbtn {
  top: 12px;
  right: 12px;
  width: 32px;
  height: 32px;
  font-size: 18px;
  z-index: 10;
  background: rgba(0, 0, 0, 0.05);
  border-radius: 50%;
  transition: all 0.2s;
}

.modern-dialog .el-dialog__headerbtn:hover {
  background: rgba(0, 0, 0, 0.1);
}

.modern-dialog .el-dialog__headerbtn .el-dialog__close {
  color: #666;
}

.modern-dialog .el-dialog__headerbtn:hover .el-dialog__close {
  color: #333;
}

/* 移动端弹窗宽度适配 */
@media (max-width: 480px) {
  .modern-dialog .el-dialog {
    width: calc(100vw - 30px) !important;
    max-width: calc(100vw - 30px) !important;
    margin: 15px auto !important;
    border-radius: 12px;
  }
  
  .modern-dialog .el-dialog__headerbtn {
    top: 8px;
    right: 8px;
    width: 28px;
    height: 28px;
    font-size: 16px;
  }
}

/* 额外的移动端适配 */
@media (max-width: 480px) {
  .modern-dialog .el-dialog {
    width: 90% !important;
  }
}
</style>
