<template>
  <div class="search-page">
    <StarBackground />
    
    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="logo" @click="$router.push('/')">EasyJob</div>
      
      <div class="nav-center">
        <!-- 搜索框 -->
        <div class="search-box">
          <input 
            v-model="keyword"
            type="search" 
            placeholder="搜索文章、作者..."
            @keyup.enter="handleSearch"
            @keydown.enter="handleSearch"
            @search="handleSearch"
            enterkeyhint="search"
          >
          <button class="search-btn" @click="handleSearch">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
            </svg>
          </button>
        </div>
      </div>
      
      <div class="nav-right">
        <button class="nav-btn" @click="$router.push('/')">首页</button>
      </div>
    </nav>

    <div class="container">
      <!-- 搜索信息 -->
      <div class="search-header">
        <h1>搜索结果</h1>
        <p class="search-info" v-if="keyword">
          关键词 "<span class="highlight">{{ keyword }}</span>" 共找到 <span class="highlight">{{ total }}</span> 条结果
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
        <div class="sort-options">
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
      <div v-if="loading" class="loading-state">搜索中...</div>
      
      <div v-else-if="results.length === 0 && !loading" class="empty-state">
        <div class="empty-icon">🔍</div>
        <p>未找到相关内容</p>
        <p class="empty-tip">换个关键词试试吧</p>
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
                <div 
                  v-else 
                  class="no-cover-placeholder"
                  :style="{ background: '#e8e8e8' }"
                >
                  <span class="placeholder-title">{{ stripHtmlTags(item.title) }}</span>
                </div>
              </div>
            </div>
            <div class="article-content">
              <h3 class="article-title" v-html="item.title"></h3>
              <p class="article-summary" v-html="item.summary || ''"></p>
              <div class="article-tags" v-if="item.tags">
                <span 
                  v-for="(tag, index) in parseTags(item.tags)" 
                  :key="index" 
                  class="tag"
                  v-html="tag"
                ></span>
              </div>
              <div class="article-meta">
                <div class="author-info" @click.stop="viewUser(item.userId)">
                  <img :src="getAvatarUrl(item.authorAvatar)" class="author-avatar" @error="handleAvatarError">
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
            <img :src="getAvatarUrl(item.avatar)" class="user-avatar" @error="handleAvatarError">
            <div class="user-info">
              <h3 class="user-name" v-html="highlightKeyword(item.nickName)"></h3>
              <p class="user-intro">{{ item.personIntroduction || '这个人很懒，什么都没有留下~' }}</p>
              <div class="user-stats">
                <span>{{ item.followerCount || 0 }} 粉丝</span>
                <span>{{ item.articleCount || 0 }} 文章</span>
              </div>
            </div>
            <button class="follow-btn" @click.stop="toggleFollow(item)">
              {{ item.isFollowing ? '已关注' : '关注' }}
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
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StarBackground from '../components/StarBackground.vue'
import request from '../utils/request'
import { getThumbUrl } from '../utils/image'

const route = useRoute()
const router = useRouter()

const keyword = ref('')
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
  if (!keyword.value.trim()) return
  
  loading.value = true
  results.value = []
  
  try {
    const params: any = {
      keyword: keyword.value.trim(),
      pageNo: currentPage.value,
      pageSize: pageSize.value,
      highlight: true
    }
    
    // 排序类型: 0=点赞, 1=时间, 2=评论, 3=收藏, 空=相关度
    if (sortBy.value !== '') {
      params.orderType = parseInt(sortBy.value)
    }
    
    console.log('发送搜索请求, 参数:', params)
    console.log('请求URL:', window.location.origin + '/api/search')
    const startTime = Date.now()
    const res = await request.get('/search', { params })
    console.log('搜索结果:', res, '耗时:', Date.now() - startTime, 'ms')
    
    if (res.code === 200 && res.data) {
      results.value = res.data.records || res.data.list || []
      total.value = res.data.total || 0
      console.log('解析后结果数:', results.value.length, '总数:', total.value)
    } else {
      console.warn('响应异常:', res)
    }
  } catch (error) {
    console.error('搜索失败:', error)
    alert('搜索请求失败: ' + (error as Error).message)
  } finally {
    loading.value = false
  }
}

// 点击搜索
function handleSearch() {
  if (!keyword.value.trim()) return
  currentPage.value = 1
  router.push(`/search?keyword=${encodeURIComponent(keyword.value.trim())}`)
}

// 切换标签
function changeTab(tab: string) {
  currentTab.value = tab
  currentPage.value = 1
  doSearch()
}

// 切换页码
function changePage(page: number) {
  currentPage.value = page
  doSearch()
  window.scrollTo(0, 0)
}

// 高亮关键词
function highlightKeyword(text: string): string {
  if (!text || !keyword.value) return text || ''
  const regex = new RegExp(`(${keyword.value})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
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
  try {
    const url = user.isFollowing 
      ? `/user/${user.userId}/unfollow`
      : `/user/${user.userId}/follow`
    
    const res = await request.post(url)
    if (res.code === 200) {
      user.isFollowing = !user.isFollowing
    }
  } catch (error) {
    console.error('操作失败:', error)
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

function getAvatarUrl(url: string | undefined): string {
  if (!url) return 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
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

function handleAvatarError(e: Event) {
  const target = e.target as HTMLImageElement
  if (target.dataset.errorHandled) return
  target.dataset.errorHandled = 'true'
  target.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
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
watch(() => route.query.keyword, (newKeyword) => {
  if (newKeyword) {
    keyword.value = String(newKeyword)
    currentPage.value = 1
    doSearch()
  }
}, { immediate: true })

onMounted(() => {
  if (route.query.keyword) {
    keyword.value = String(route.query.keyword)
    doSearch()
  }
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
  background: #f5f7fa;
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
  color: #409eff;
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
  border-color: #409eff;
  background: white;
}

.search-btn {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 34px;
  height: 34px;
  background: #409eff;
  border: none;
  border-radius: 50%;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.search-btn:hover {
  background: #66b1ff;
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

.result-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s;
}

.result-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15);
}

/* 文章卡片 */
.article-card {
  display: flex;
}

.article-cover {
  width: 200px;
  height: 140px;
  flex-shrink: 0;
  background: #e8e8e8;
  position: relative;
  overflow: hidden;
  border-radius: 16px 0 0 16px;
}

.cover-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
  background: #f0f0f0;
}

.article-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
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

.no-cover-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  text-align: center;
  background: #e8e8e8;
}

.placeholder-title {
  color: #666;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.3;
  max-width: 100%;
  word-break: break-word;
  text-align: center;
  padding: 0 4px;
}

.no-cover {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
}

.article-content {
  flex: 1;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.article-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin-bottom: 10px;
}

.article-title :deep(mark) {
  background: rgba(79, 172, 254, 0.3);
  color: #4facfe;
  padding: 0 2px;
  border-radius: 2px;
}

.article-summary {
  font-size: 14px;
  color: #666;
  line-height: 1.6;
  flex: 1;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.article-summary :deep(mark) {
  background: rgba(79, 172, 254, 0.3);
  color: #4facfe;
}

/* ES高亮样式 */
.article-title :deep(.highlight),
.article-summary :deep(.highlight),
.article-tags :deep(.highlight) {
  background: linear-gradient(135deg, rgba(79, 172, 254, 0.3), rgba(0, 242, 254, 0.3));
  color: #00d4ff;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 600;
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
  padding: 4px 12px;
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  border-radius: 12px;
  font-size: 12px;
  transition: all 0.3s;
}

.article-tags .tag:hover {
  background: rgba(102, 126, 234, 0.2);
}

.article-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 15px;
}

.author-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  margin: -4px -8px;
  border-radius: 6px;
  transition: background 0.2s;
}

.author-info:hover {
  background: rgba(79, 172, 254, 0.1);
}

.author-info:hover .author-name {
  color: #4facfe;
}

.author-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
}

.author-name {
  font-size: 13px;
  color: #666;
}

.stats {
  display: flex;
  gap: 15px;
  font-size: 13px;
  color: #999;
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

.follow-btn {
  padding: 8px 24px;
  border: 1px solid #4facfe;
  background: white;
  color: #4facfe;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.follow-btn:hover {
  background: #4facfe;
  color: white;
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
    padding: 15px;
  }
  
  .article-cover {
    width: 100%;
    height: 150px;
    border-radius: 8px;
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
  
  .article-card {
    padding: 12px;
  }
  
  .article-info h3 {
    font-size: 15px;
  }
  
  .article-summary {
    font-size: 12px;
  }
  
  .article-cover {
    height: 140px;
  }
  
  .article-meta {
    font-size: 11px;
  }
}
</style>
