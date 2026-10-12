<template>
  <div class="search-page">
    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="logo" @click="$router.push('/')">EasyJob</div>
      
      <div class="nav-center">
        <!-- 搜索框 -->
        <SearchBox v-model="keyword" @search="handleSearch" />
      </div>
      
      <AppNavigation />
    </nav>

    <div class="container">
      <!-- 搜索信息 -->
      <div class="search-header">
        <h1>搜索结果</h1>
        <p class="search-info" v-if="submittedKeyword">
          关键词 "<span class="highlight">{{ submittedKeyword }}</span>"<template v-if="!loading && !searchError"> 共找到 <span class="highlight">{{ total }}</span> {{ currentTab === 'article' ? '篇文章' : '位用户' }}</template>
        </p>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar">
        <div class="filter-tabs">
          <button 
            v-for="tab in tabs" 
            :key="tab.value"
            :class="['filter-tab', { active: currentTab === tab.value }]"
            @click="changeTab(tab.value)"
          >
            {{ tab.label }}
          </button>
        </div>
        <div v-if="currentTab === 'article'" class="sort-options">
          <span>排序：</span>
          <select v-model="sortBy" @change="doSearch">
            <option value="">相关度</option>
            <option value="1">最新发布</option>
            <option value="0">最多点赞</option>
            <option value="3">最多收藏</option>
            <option value="2">最多评论</option>
          </select>
        </div>
      </div>

      <!-- 搜索结果 -->
      <ContentState v-if="loading" kind="loading" title="正在搜索" />
      <ContentState v-else-if="searchError" kind="error" title="搜索暂时未完成" :description="searchError" @retry="doSearch" />
      
      <div v-else-if="results.length === 0 && !loading" class="empty-state">
        <div class="empty-icon">🔍</div>
        <p>{{ submittedKeyword ? (currentTab === 'article' ? '未找到相关文章' : '未找到相关用户') : '输入关键词开始搜索' }}</p>
        <p v-if="submittedKeyword" class="empty-tip">换个关键词试试吧</p>
      </div>

      <div v-else class="result-list">
        <!-- 文章结果 -->
        <template v-if="currentTab === 'article'">
          <div 
            v-for="item in results" 
            :key="item.articleId"
            class="result-card article-card"
            @click="viewArticle(item.articleId)"
          >
            <div class="article-cover">
              <div class="cover-wrapper">
                <img 
                  v-if="item.coverImage" 
                  v-lazyload="{
                    src: getThumbUrl(getImageUrl(item.coverImage)) || getImageUrl(item.coverImage),
                    fallback: getImageUrl(item.coverImage)
                  }"
                  alt="封面"
                  @error="handleCoverError($event, item.coverImage)"
                >
                <CoverPlaceholder v-else :title="stripHtmlTags(item.title)" />
              </div>
            </div>
            <div class="article-content">
              <h3 class="article-title"><SearchHighlight :text="item.title" :keyword="submittedKeyword" es-markers /></h3>
              <p class="article-summary"><SearchHighlight :text="item.summary || ''" :keyword="submittedKeyword" /></p>
              <div class="article-tags" v-if="item.tags">
                <span 
                  v-for="(tag, index) in parseTags(item.tags)" 
                  :key="index" 
                  class="tag"
                ><SearchHighlight :text="tag" :keyword="submittedKeyword" /></span>
              </div>
              <div class="article-meta">
                <span v-if="item.requiredLevel > 0" class="reading-level-badge">L{{ item.requiredLevel }} 阅读</span>
                <div class="author-info" @click.stop="viewUser(item.userId)">
                  <img :src="avatarUrl(item.authorAvatar, item.authorName)" alt="" class="author-avatar" @error="onAvatarError($event, item.authorName)">
                  <span class="author-name">{{ item.authorName || '匿名' }}</span>
                </div>
                <div class="stats">
                  <span>{{ item.viewCount || 0 }} 浏览</span>
                  <span>{{ item.likeCount || 0 }} 点赞</span>
                  <span>{{ formatDate(item.createTime) }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 用户结果 -->
        <template v-if="currentTab === 'user'">
          <div 
            v-for="item in results" 
            :key="item.userId"
            class="result-card user-card"
            @click="viewUser(item.userId)"
          >
            <img :src="avatarUrl(item.avatar, item.nickName)" :alt="`${item.nickName || '用户'}的头像`" class="user-avatar" @error="onAvatarError($event, item.nickName)">
            <div class="user-info">
              <h3 class="user-name"><SearchHighlight :text="item.nickName" :keyword="submittedKeyword" /></h3>
              <p class="user-intro">{{ item.personIntroduction || '这个人很懒，什么都没有留下~' }}</p>
              <div class="user-stats">
                <span>{{ item.followerCount || 0 }} 粉丝</span>
                <span>{{ item.articleCount || 0 }} 文章</span>
              </div>
            </div>
            <button v-if="String(item.userId) !== currentUserId" class="follow-btn" :class="{ following: item.isFollowing }" :disabled="followingIds.has(String(item.userId))" @click.stop="toggleFollow(item)">
              {{ followingIds.has(String(item.userId)) ? '处理中…' : item.isFollowing ? '已关注' : '关注' }}
            </button>
          </div>
        </template>
      </div>

      <!-- 分页 -->
      <div v-if="totalPages > 1" class="pagination">
        <button 
          class="page-btn" 
          :disabled="currentPage === 1"
          @click="changePage(currentPage - 1)"
        >
          上一页
        </button>
        <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
        <button 
          class="page-btn" 
          :disabled="currentPage === totalPages"
          @click="changePage(currentPage + 1)"
        >
          下一页
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppNavigation from '@/components/AppNavigation.vue'
import SearchBox from '@/components/SearchBox.vue'
import ContentState from '@/components/ContentState.vue'
import { ref, computed, watch, onUnmounted } from 'vue'
import { latestRequest } from '@/utils/latestRequest'
import { notify, errorMessage } from '@/utils/feedback'
import SearchHighlight from '@/components/SearchHighlight.vue'
import CoverPlaceholder from '@/components/CoverPlaceholder.vue'
import { eventBus, EVENT_AUTH_CHANGED, EVENT_AUTH_EXPIRED } from '@/utils/eventBus'
import { useRoute, useRouter } from 'vue-router'
import request from '../utils/request'
import { getThumbUrl } from '../utils/image'
import { avatarUrl, onAvatarError } from '../utils/avatar'

const route = useRoute()
const router = useRouter()

const keyword = ref('')
const submittedKeyword = ref('')
const searchError = ref('')
const requests = latestRequest()
const currentUserId = ref(localStorage.getItem('token') ? localStorage.getItem('userId') || '' : '')
const followingIds = ref(new Set<string>())
const results = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)
const currentTab = ref('article')
const sortBy = ref('')  // 空字符串表示相关度排序

const tabs = [
  { label: '文章', value: 'article' },
  { label: '用户', value: 'user' }
]

const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

// 搜索
async function doSearch() {
  const ticket = requests.begin()
  searchError.value = ''
  results.value = []
  total.value = 0
  if (!submittedKeyword.value) { loading.value = false; return }
  loading.value = true
  
  try {
    const params: any = {
      keyword: submittedKeyword.value,
      pageNo: currentPage.value,
      pageSize: pageSize.value,
      highlight: true
    }
    
    // 排序类型: 0=点赞, 1=时间, 2=评论, 3=收藏, 空=相关度
    if (currentTab.value === 'article' && sortBy.value !== '') {
      params.orderType = parseInt(sortBy.value)
    }
    
    const res = await request.get(currentTab.value === 'user' ? '/search/users' : '/search', { params, signal: ticket.signal })
    if (!ticket.isCurrent()) return
    
    if (res.code === 200 && res.data) {
      results.value = res.data.records || res.data.list || []
      total.value = res.data.total || 0
    } else {
      throw new Error('搜索结果暂时不可用，请重新加载')
    }
  } catch (error) {
    if (ticket.isCurrent()) searchError.value = errorMessage(error, '网络连接失败，请稍后重试')
  } finally {
    if (ticket.isCurrent()) loading.value = false
  }
}

// 点击搜索
function handleSearch() {
  if (!keyword.value.trim()) return
  currentPage.value = 1
  if (String(route.query.keyword || '') === keyword.value.trim()) {
    doSearch()
    return
  }
  router.push({ path: '/search', query: { keyword: keyword.value.trim(), type: currentTab.value } })
}

// 切换标签
function changeTab(tab: string) {
  if (currentTab.value === tab) return
  router.replace({ query: { ...route.query, type: tab } })
}

// 切换页码
function changePage(page: number) {
  currentPage.value = page
  doSearch()
  window.scrollTo(0, 0)
}

// 解析标签
function parseTags(tags: string): string[] {
  if (!tags) return []
  return tags.split(',').filter(t => t.trim())
}

// 查看文章
function viewArticle(articleId: string) {
  window.open(`/article/${articleId}`, '_blank')
}
function viewUser(userId: string | number | undefined) {
  console.log('点击查看用户, userId:', userId)
  if (!userId || userId === 'undefined' || userId === 'null') {
    console.warn('用户ID无效:', userId)
    return
  }
  router.push(`/user-space/${userId}`)
}

// 关注/取关
async function toggleFollow(user: any) {
  if (!localStorage.getItem('token')) { router.push({ path: '/', query: { login: 'true', redirect: route.fullPath } }); return }
  const id = String(user.userId)
  if (followingIds.value.has(id)) return
  followingIds.value.add(id)
  const actingUser = currentUserId.value
  try {
    const url = user.isFollowing 
      ? `/user/${user.userId}/unfollow`
      : `/user/${user.userId}/follow`
    
    const res = await request.post(url)
    if (res.code === 200) {
      if (actingUser === currentUserId.value) user.isFollowing = !user.isFollowing
    }
  } catch (error) {
    notify.error(errorMessage(error, '关注操作失败，请重试'))
  } finally {
    followingIds.value.delete(id)
  }
}

// 去除HTML标签
function stripHtmlTags(str: string): string {
  if (!str) return ''
  return str.replace(/<[^>]*>/g, '')
}

// 图片处理
function getImageUrl(url: string | undefined): string {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/uploads')) return url
  return url
}

function handleCoverError(e: Event, originalCover?: string) {
  const target = e.target as HTMLImageElement
  const currentSrc = target.src
  
  // 缩略图加载失败，回退到原图
  if (currentSrc.includes('/thumbnails/') && originalCover) {
    target.src = getImageUrl(originalCover)
    return
  }
  
  // 原图也加载失败，隐藏图片
  target.style.display = 'none'
}

// 格式化日期
function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
  if (diff < 2592000000) return Math.floor(diff / 86400000) + '天前'
  
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

// 监听路由变化
watch(() => [route.query.keyword, route.query.type], ([newKeyword, type]) => {
    currentTab.value = type === 'user' ? 'user' : 'article'
    keyword.value = String(newKeyword || '').trim()
    submittedKeyword.value = keyword.value
    currentPage.value = 1
    doSearch()
}, { immediate: true })

function authChanged() {
  currentUserId.value = localStorage.getItem('token') ? localStorage.getItem('userId') || '' : ''
  if (currentTab.value === 'user') doSearch()
}
eventBus.on(EVENT_AUTH_CHANGED, authChanged)
eventBus.on(EVENT_AUTH_EXPIRED, authChanged)
onUnmounted(() => {
  requests.cancel()
  eventBus.off(EVENT_AUTH_CHANGED, authChanged)
  eventBus.off(EVENT_AUTH_EXPIRED, authChanged)
})

</script>

<style scoped>
.search-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
}

.search-page::before {
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
  align-items: center;
  padding: 0 50px;
  z-index: 1000;
}

.logo {
  font-size: 28px;
  font-weight: bold;
  color: var(--ej-accent);
  cursor: pointer;
  flex-shrink: 0;
}

.nav-center {
  flex: 1;
  display: flex;
  justify-content: center;
  margin: 0 20px;
}

.nav-menu {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-left: auto;
}

.search-box {
  flex: 1;
  max-width: 500px;
  margin: 0;
  position: relative;
}

.search-box input {
  width: 100%;
  height: 42px;
  padding: 0 50px 0 20px;
  border: 1px solid #ddd;
  border-radius: 21px;
  font-size: 15px;
  outline: none;
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
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 34px;
  height: 34px;
  background: var(--ej-accent);
  border: none;
  border-radius: 50%;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-btn:hover {
  background: var(--ej-ink);
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
}

.nav-btn:hover {
  background: #eee;
}

.container {
  max-width: 900px;
  margin: 100px auto 50px;
  padding: 0 20px;
}

.search-header {
  margin-bottom: 25px;
}

.search-header h1 {
  color: #333;
  font-size: 28px;
  margin-bottom: 10px;
}

.search-info {
  color: #666;
  font-size: 16px;
}

.search-info .highlight {
  color: #4facfe;
  font-weight: 600;
}

.filter-bar {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  padding: 15px 20px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.filter-tabs {
  display: flex;
  gap: 10px;
}

.filter-tab {
  padding: 8px 20px;
  border: 1px solid #ddd;
  background: white;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  transition: all 0.3s;
}

.filter-tab:hover {
  border-color: #4facfe;
  color: #4facfe;
}

.filter-tab.active {
  background: #4facfe;
  border-color: #4facfe;
  color: white;
}

.sort-options {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #666;
}

.sort-options select {
  padding: 6px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  cursor: pointer;
}

.loading-state,
.empty-state {
  text-align: center;
  padding: 80px 20px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  color: #666;
}

.empty-icon {
  font-size: 60px;
  margin-bottom: 20px;
}

.empty-tip {
  font-size: 14px;
  color: #999;
  margin-top: 10px;
}

.result-list {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

/* 卡片底色、边框、悬停与高亮配色见 styles/theme.css */
.result-card {
  overflow: hidden;
  cursor: pointer;
}

/* 文章卡片：左侧封面是嵌在卡片内的小画框，没有封面时显示与首页一致的描边大字占位 */
.article-card {
  --card-paper: #f3a093;
  display: flex;
}

.article-card:nth-child(3n+2) {
  --card-paper: #b4a7ff;
}

.article-card:nth-child(3n+3) {
  --card-paper: #d3f795;
}

.article-cover {
  --cover-glyph-size: 84px;
  width: 184px;
  flex-shrink: 0;
  padding: 14px 0 14px 14px;
}

.cover-wrapper {
  width: 100%;
  height: 100%;
  min-height: 128px;
  position: relative;
  overflow: hidden;
  background: var(--card-paper);
}

.article-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  filter: saturate(.85);
  transition: opacity 0.3s ease-in-out;
}

/* 懒加载状态样式 */
.article-cover img.lazy-loading {
  opacity: 0;
}

.article-cover img.lazy-loaded {
  opacity: 1;
}

.article-cover img.lazy-error {
  opacity: 0.5;
}

.article-content {
  flex: 1;
  min-width: 0;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
}

.article-title {
  font-size: 18px;
  font-weight: 800;
  line-height: 1.5;
  letter-spacing: -.02em;
  color: var(--ej-ink);
  margin-bottom: 8px;
}

.article-summary {
  font-size: 13px;
  color: #47453f;
  line-height: 1.75;
  flex: 1;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 文章标签 */
.article-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.article-tags .tag {
  display: inline-block;
  padding: 3px 11px;
  font-size: 12px;
}

.article-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--ej-hairline);
}

.author-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  cursor: pointer;
  padding: 4px 10px 4px 4px;
  margin: -4px -10px -4px -4px;
  border-radius: 999px;
  transition: background 0.2s;
}

.author-info:hover {
  background: var(--studio-lime-soft);
}

.author-avatar {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 50%;
  object-fit: cover;
  border: 1px solid var(--ej-ink);
}

.author-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ej-ink);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.stats {
  display: flex;
  gap: 14px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--ej-muted);
}

/* 用户卡片 */
.user-card {
  display: flex;
  align-items: center;
  padding: 20px;
}

.user-avatar {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}

.user-info {
  flex: 1;
  margin-left: 20px;
}

.user-name {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin-bottom: 6px;
}

.user-name :deep(mark) {
  background: rgba(79, 172, 254, 0.3);
  color: #4facfe;
}

.user-intro {
  font-size: 14px;
  color: #666;
  margin-bottom: 8px;
}

.user-stats {
  display: flex;
  gap: 15px;
  font-size: 13px;
  color: #999;
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
  border-color: #4facfe;
  color: #4facfe;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  color: #666;
  font-size: 14px;
}

@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 55px;
  }
  
  .logo {
    font-size: 20px;
  }
  
  .nav-center {
    margin: 0 10px;
    flex: 1;
  }
  
  .search-box {
    margin: 0;
    max-width: none;
  }
  
  .search-box input {
    height: 36px;
    font-size: 13px;
  }
  
  .nav-menu {
    margin-left: 10px;
  }
  
  .nav-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
  
  .main-content {
    padding: 20px 15px;
    margin-top: 75px;
  }
  
  .article-card {
    flex-direction: column;
  }
  
  .article-cover {
    --cover-glyph-size: 104px;
    width: 100%;
    height: 172px;
    padding: 12px 12px 0;
  }

  .article-content {
    padding: 14px 16px 16px;
  }
  
  .article-info h3 {
    font-size: 16px;
  }
  
  .article-summary {
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
  
  .search-box input {
    height: 34px;
    font-size: 12px;
    padding: 0 35px 0 12px;
  }
  
  .nav-btn {
    padding: 5px 10px;
    font-size: 11px;
  }
  
  .main-content {
    padding: 15px 10px;
    margin-top: 65px;
  }
  
  .search-header h2 {
    font-size: 18px;
  }
  
  .filter-tabs {
    gap: 8px;
    flex-wrap: wrap;
  }
  
  .filter-tab {
    padding: 6px 12px;
    font-size: 12px;
  }
  
  .article-info h3 {
    font-size: 15px;
  }
  
  .article-summary {
    font-size: 12px;
  }
  
  .article-cover {
    height: 156px;
  }

  .stats span:last-child {
    display: none;
  }
  
  .article-meta {
    font-size: 11px;
  }
}
</style>
