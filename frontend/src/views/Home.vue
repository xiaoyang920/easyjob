<template>
  <div class="home-page">
    <!-- 导航栏 -->
    <div class="navbar">
      <div class="logo" @click="$router.push('/')">
        <svg class="logo-icon" viewBox="0 0 1024 1024" fill="currentColor">
          <path d="M512 1024c282.771692 0 512-229.228308 512-512S794.771692 0 512 0 0 229.228308 0 512s229.228308 512 512 512z m0-59.076923C261.858462 964.923077 59.076923 762.141538 59.076923 512S261.858462 59.076923 512 59.076923s452.923077 202.781538 452.923077 452.923077-202.781538 452.923077-452.923077 452.923077z"/>
          <path d="M464.945231 748.642462c15.399385 3.042462 31.133538 4.588308 47.054769 4.588307 133.228308 0 241.230769-108.002462 241.230769-241.230769S645.228308 270.769231 512 270.769231 270.769231 378.771692 270.769231 512c0 15.921231 1.545846 31.655385 4.588307 47.054769a24.615385 24.615385 0 0 0 48.295385-9.550769A193.053538 193.053538 0 0 1 320 512c0-106.043077 85.956923-192 192-192S704 405.956923 704 512 618.043077 704 512 704c-12.701538 0-25.245538-1.230769-37.494154-3.652923a24.615385 24.615385 0 1 0-9.550769 48.295385z"/>
          <path d="M512 512m-78.769231 0a78.769231 78.769231 0 1 0 157.538462 0 78.769231 78.769231 0 1 0-157.538462 0Z"/>
          <path d="M510.385231 498.294154C396.465231 543.123692 320 653.351385 320 777.846154a24.615385 24.615385 0 1 0 49.230769 0 251.145846 251.145846 0 0 1 159.182769-233.737846 24.615385 24.615385 0 0 0-18.018461-45.814154z"/>
        </svg>
        <span class="logo-text">EasyJob</span>
      </div>
      
      <!-- 搜索框 -->
      <SearchBox v-model="searchKeyword" @search="handleSearch" />
      
      <AppNavigation :authenticated="isLogin" :avatar="avatar" :nickname="nickName" :stats="userStats" :unread-messages="totalUnreadCount" @login="showLoginDialog = true" @register="showRegisterDialog = true" @logout="logout" />
    </div>

    <!-- 登录弹窗 -->
    <el-dialog
      v-model="showLoginDialog"
      title=""
      :width="dialogWidth"
      :show-close="true"
      destroy-on-close
      class="modern-dialog"
    >
      <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
    </el-dialog>

    <!-- 注册弹窗 -->
    <el-dialog
      v-model="showRegisterDialog"
      title=""
      :width="dialogWidth"
      :show-close="true"
      destroy-on-close
      class="modern-dialog"
    >
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
                <div 
                  v-else 
                  class="no-cover-placeholder"
                  :style="{ background: '#e8e8e8' }"
                >
                  <span class="placeholder-title">{{ stripHtmlTags(article.title) }}</span>
                </div>
                
                <!-- 封面上的悬浮信息 -->
                <div class="cover-overlay">
                  <div class="overlay-stats">
                    <span class="stat-item">
                      <svg viewBox="0 0 1024 1024" fill="white">
                        <path d="M675.328 117.717333A425.429333 425.429333 0 0 0 512 85.333333C276.352 85.333333 85.333333 276.352 85.333333 512s191.018667 426.666667 426.666667 426.666667 426.666667-191.018667 426.666667-426.666667c0-56.746667-11.093333-112-32.384-163.328a21.333333 21.333333 0 0 0-39.402667 16.341333A382.762667 382.762667 0 0 1 896 512c0 212.074667-171.925333 384-384 384S128 724.074667 128 512 299.925333 128 512 128c51.114667 0 100.8 9.984 146.986667 29.12a21.333333 21.333333 0 0 0 16.341333-39.402667zM456.704 305.92C432.704 289.152 405.333333 303.082667 405.333333 331.797333v360.533334c0 28.586667 27.541333 42.538667 51.370667 25.856l252.352-176.768c21.76-15.253333 21.632-43.541333 0-58.709334l-252.373333-176.768z m-8.597333 366.72V351.466667l229.269333 160.597333-229.269333 160.597333z"/>
                      </svg>
                      {{ formatNumber(article.viewCount || 0) }}
                    </span>
                    <span class="stat-item">
                      <svg width="14" height="14" viewBox="0 0 1024 1024" fill="white">
                        <path d="M939.358251 423.424662c-23.01825-37.252439-62.924121-60.779272-107.019409-63.209624-2.755764-0.38681-5.510504-0.579191-8.347109-0.579191l-152.202471-0.121773c6.649444-28.975938 10.015098-58.653865 10.015098-88.657202 0-28.223808-3.213181-57.139372-9.556657-85.952604-0.447185-2.043542-1.098008-4.006244-1.932002-5.866614-15.820314-57.302077-67.37755-96.841605-127.282918-96.841605-72.827679 0-132.081201 59.254545-132.081201 132.081201 0 3.334955 0.132006 6.66991 0.406253 10.015098-2.196015 57.211003-32.108279 109.947088-80.269162 141.363611-14.447037 9.42465-18.524912 28.773324-9.099239 43.220361 9.414417 14.437827 28.752858 18.535145 43.220361 9.099239 65.811892-42.925648 106.429984-115.325585 108.656699-193.684234 0.030699-1.332345-0.010233-2.663666-0.14224-3.996011-0.203638-2.012843-0.304945-4.016477-0.304945-6.019087 0-38.381146 31.233352-69.614497 69.614497-69.614497 32.57593 0 60.474326 22.204721 67.824735 53.997821 0.356111 1.534959 0.823761 3.019777 1.402953 4.453429 4.696975 22.814612 7.076162 45.579081 7.076162 67.743894 0 37.485753-6.222725 74.352405-18.494213 109.592001-3.324722 9.546424-1.819438 20.111037 4.02671 28.345582 5.856381 8.245801 15.332197 13.146415 25.448602 13.156648l193.226816 0.101307c1.423419 0.264013 2.857071 0.426719 4.300956 0.477884 24.116257 0.9967 45.935192 13.614066 58.603723 34.090423 7.838525 12.31242 11.438517 26.800389 10.431583 41.939181-0.080841 0.945535-0.121773 1.911536-0.11154 2.877537 0 0.854461 0.040932 1.697665 0.11154 2.53166 0.010233 0.335644-0.030699 0.661056-0.11154 0.976234-0.101307 0.376577-0.193405 0.772596-0.284479 1.159406l-74.972529 330.391802c-0.914836 1.281179-1.738597 2.6432-2.449795 4.046153-5.937223 11.762905-14.660908 21.48329-25.346271 28.172643-10.746762 6.812149-23.059182 10.614755-35.757388 11.06194-0.854461-0.061398-513.766226-0.224104-513.766226-0.224104-0.467651-0.020466-0.935302-0.030699-1.402953-0.030699 0 0-111.01542 0.172939-112.718201 0.457418-1.932002 0-3.446495-1.50426-3.446495-3.415796l0.299829-416.334173c0-1.901303 1.545192-3.446495 3.01466-3.456728l1.245364 0.121773c1.174756 0.132006 2.653433 0.284479 3.52836 0.193405l83.82822-0.222057 0 339.367221c0 17.253966 13.979386 31.233352 31.233352 31.233352s31.233352-13.979386 31.233352-31.233352L281.009092 435.350273c0-1.778506 0-8.631588 0-10.411117 0-17.253966-13.979386-30.928407-31.233352-30.928407-1.50426 0-117.547183 0.304945-119.402437 0.304945-36.34272 0-65.913199 29.566386-65.913199 65.893756l-0.299829 416.334173c0 36.337603 29.571503 65.902966 65.913199 65.902966 2.541893 0 111.406323-0.457418 111.406323-0.457418 0.457418 0.020466 0.925069 0.030699 1.382487 0.030699 0 0 511.458671 0.274246 512.505513 0.274246 25.469068 0 50.296523-7.197936 71.647807-20.73116 19.612687-12.281721 35.777855-29.881564 46.839795-50.967812 3.660366-5.622044 6.435573-11.875468 8.256034-18.615986 0.11154-0.416486 0.213871-0.823761 0.304945-1.240247l74.881454-330.340637c1.596358-6.212492 2.257413-12.586666 2.00261-18.992563C960.892707 473.366098 953.948551 446.331371 939.358251 423.424662z"/>
                        <path d="M450.027553 518.650467c-17.253966 0-31.233352 13.979386-31.233352 31.233352l0 30.470989c0 17.253966 13.979386 31.233352 31.233352 31.233352 17.253966 0 31.233352-13.979386 31.233352-31.233352l0-30.470989C481.260905 532.629853 467.281519 518.650467 450.027553 518.650467z"/>
                        <path d="M693.805696 518.650467c-17.253966 0-31.233352 13.979386-31.233352 31.233352l0 30.470989c0 17.253966 13.979386 31.233352 31.233352 31.233352 17.253966 0 31.233352-13.979386 31.233352-31.233352l0-30.470989C725.039048 532.629853 711.058638 518.650467 693.805696 518.650467z"/>
                        <path d="M648.940882 660.09492c-14.304797-9.393951-33.592073-5.398964-43.159986 8.763594-0.132006 0.193405-13.614066 19.754926-34.171264 19.754926-19.98824 0-32.423457-18.09717-33.266661-19.368116-9.17087-14.427594-28.254507-18.809391-42.834574-9.770528-14.650675 9.109472-19.155269 28.366048-10.055007 43.016723 11.214413 18.047028 41.96988 48.588625 86.156242 48.588625 43.962258 0 75.104535-30.318516 86.572728-48.222281C667.404396 688.461991 663.216004 669.500127 648.940882 660.09492z"/>
                      </svg>
                      {{ formatNumber(article.likeCount || 0) }}
                    </span>
                  </div>
                </div>
              </div>
              
                <div class="article-info">
                  <span v-if="article.requiredLevel > 0" class="reading-level-badge">{{ article.readableNow === false ? `需 L${article.requiredLevel} 解锁` : `L${article.requiredLevel} · 可读` }}</span>
                <div class="studio-card-index"><span>{{ String(articleIndex + 1).padStart(2, '0') }} / 文章</span><span aria-hidden="true">↗</span></div>
                <div class="article-title">{{ article.title }}</div>
                <p v-if="article.summary" class="article-deck">{{ stripHtmlTags(article.summary) }}</p>
                <div v-if="currentSort === 'recommend' && article.recommendationReason" class="recommendation-reason">{{ article.recommendationReason }}</div>
                <div v-if="isLogin && currentSort==='recommend'" class="recommend-feedback" @click.stop @keydown.stop><el-dropdown trigger="click" @command="(kind:string)=>recommendationFeedback(article.articleId || article.id,kind)"><button :disabled="!!feedbackBusy" :aria-label="`调整《${article.title}》的推荐`">调整推荐 ···</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="not_interested">不感兴趣</el-dropdown-item><el-dropdown-item command="hide_author">不再推荐该作者</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
                <div class="article-byline"><span>{{ article.authorName || article.nickName || '社区创作者' }}</span><span>{{ formatNumber(article.viewCount || 0) }} 次阅读</span></div>
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
import AppNavigation from '@/components/AppNavigation.vue'
import SearchBox from '@/components/SearchBox.vue'
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import LoginForm from '@/components/LoginForm.vue'
import RegisterForm from '@/components/RegisterForm.vue'
import HomeStudio from '@/components/HomeStudio.vue'
import request from '@/utils/request'
import { getThumbUrl, onThumbError } from '@/utils/image'
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

// 获取用户头像URL
function getAvatarUrl(url: string | undefined): string {
  if (!url) {
    return 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
  }
  
  // 如果是完整URL
  if (url.startsWith('http://') || url.startsWith('https://')) {
    // 如果是localhost的URL，去掉域名部分
    if (url.includes('localhost:8080')) {
      return url.replace(/https?:\/\/localhost:8080/, '')
    }
    return url
  }
  
  // 如果是相对路径，直接返回
  if (url.startsWith('/uploads')) {
    return url
  }
  
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
function handleLoginSuccess() {
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
  ElMessage.success('登录成功')
  
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
  showLoginDialog.value = true
  ElMessage.success('注册成功，请登录')
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

function handleAvatarError(e: Event) {
  const target = e.target as HTMLImageElement
  console.log('头像加载失败，使用默认头像')
  target.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
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
.recommend-preferences,.recommend-feedback button{font:inherit;font-size:12px;border:0;background:transparent;color:var(--ej-ink);cursor:pointer}.recommend-preferences:hover,.recommend-feedback button:hover{text-decoration:underline}.recommend-feedback{margin:8px 0}.recommend-feedback button:disabled{opacity:.5;cursor:wait}

.reading-filter { display:flex; align-items:center; flex-wrap:wrap; gap:10px 18px; margin:0 0 24px; font-size:12px; color:#73756b; }
.reading-filter label { display:flex; align-items:center; gap:8px; color:#171714; cursor:pointer; white-space:nowrap; }
.reading-filter input { accent-color:#9dc82f; width:16px; height:16px; }
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

.no-cover-placeholder {
  width: 100%;
  height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  text-align: center;
  background: #e8e8e8;
}

.placeholder-title {
  color: #666;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.3;
  max-width: 100%;
  word-break: break-word;
  text-align: center;
  padding: 0 4px;
}

.cover-wrapper {
  width: 100%;
  height: 180px;
  overflow: hidden;
  position: relative;
  background: #f0f0f0;
  border-radius: 12px 12px 0 0;
}

/* 封面悬浮信息 */
.cover-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 8px 10px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.7), transparent);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.overlay-stats {
  display: flex;
  gap: 15px;
  color: white;
  font-size: 14px;
  font-weight: 500;
}

.overlay-stats .stat-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.overlay-stats svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
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
  
  .placeholder-title {
    font-size: 12px;
  }
  
  .overlay-stats {
    font-size: 11px;
    gap: 8px;
  }
  
  .overlay-stats svg {
    width: 12px;
    height: 12px;
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

<style scoped>
.recommendation-reason { font-size: 12px; color: #34342b; opacity: .72; margin-top: 12px; }
</style>
