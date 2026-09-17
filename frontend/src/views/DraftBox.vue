<template>
  <div class="draft-box-page">
    <StarBackground />
    
    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="nav-left">
        <div class="logo" @click="$router.push('/')">
          <svg class="logo-icon" viewBox="0 0 1024 1024" fill="currentColor">
            <path d="M512 1024c282.771692 0 512-229.228308 512-512S794.771692 0 512 0 0 229.228308 0 512s229.228308 512 512 512z m0-59.076923C261.858462 964.923077 59.076923 762.141538 59.076923 512S261.858462 59.076923 512 59.076923s452.923077 202.781538 452.923077 452.923077-202.781538 452.923077-452.923077 452.923077z"/>
            <path d="M464.945231 748.642462c15.399385 3.042462 31.133538 4.588308 47.054769 4.588307 133.228308 0 241.230769-108.002462 241.230769-241.230769S645.228308 270.769231 512 270.769231 270.769231 378.771692 270.769231 512c0 15.921231 1.545846 31.655385 4.588307 47.054769a24.615385 24.615385 0 0 0 48.295385-9.550769A193.053538 193.053538 0 0 1 320 512c0-106.043077 85.956923-192 192-192S704 405.956923 704 512 618.043077 704 512 704c-12.701538 0-25.245538-1.230769-37.494154-3.652923a24.615385 24.615385 0 1 0-9.550769 48.295385z"/>
            <path d="M512 512m-78.769231 0a78.769231 78.769231 0 1 0 157.538462 0 78.769231 78.769231 0 1 0-157.538462 0Z"/>
            <path d="M510.385231 498.294154C396.465231 543.123692 320 653.351385 320 777.846154a24.615385 24.615385 0 1 0 49.230769 0 251.145846 251.145846 0 0 1 159.182769-233.737846 24.615385 24.615385 0 0 0-18.018461-45.814154z"/>
          </svg>
          <span class="logo-text">EasyJob</span>
        </div>
        <span class="page-title">草稿箱</span>
      </div>
      <div class="nav-right">
        <button class="nav-btn" @click="$router.push('/')">返回首页</button>
      </div>
    </nav>

    <div class="container">
      <div class="page-header">
        <h1>草稿箱</h1>
        <span class="draft-count">共 {{ drafts.length }} 篇草稿</span>
      </div>

      <div v-if="loading" class="loading-state">加载中...</div>
      
      <div v-else-if="drafts.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>
          </svg>
        </div>
        <p>暂无草稿</p>
        <button class="create-btn" @click="$router.push('/create-article')">开始创作</button>
      </div>

      <div v-else class="draft-list">
        <div 
          v-for="draft in drafts" 
          :key="draft.articleId" 
          class="draft-card"
        >
          <div class="draft-cover">
            <img 
              v-if="draft.coverImage" 
              :src="getThumbUrl(getImageUrl(draft.coverImage)) || getImageUrl(draft.coverImage)" 
              alt="封面"
              @error="handleCoverError($event, draft.coverImage)"
            >
            <div 
              v-else 
              class="no-cover-placeholder"
              :style="{ background: '#e8e8e8' }"
            >
              <span class="placeholder-title">{{ stripHtmlTags(draft.title || '无标题') }}</span>
            </div>
          </div>
          <div class="draft-content">
            <h3 class="draft-title">{{ draft.title || '无标题' }}</h3>
            <p class="draft-summary">{{ draft.summary || '暂无摘要' }}</p>
            <div class="draft-meta">
              <span>最后编辑: {{ formatDate(draft.updateTime || draft.createTime) }}</span>
            </div>
          </div>
          <div class="draft-actions">
            <button class="action-btn edit" @click="editDraft(draft.articleId)">编辑</button>
            <button class="action-btn publish" @click="publishDraft(draft.articleId)">发布</button>
            <button class="action-btn delete" @click="deleteDraft(draft.articleId)">删除</button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="drafts.length > 0" class="pagination">
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
    <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
      <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
    </el-dialog>
    <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
      <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import StarBackground from '../components/StarBackground.vue'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { getThumbUrl } from '../utils/image'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'

const router = useRouter()
const drafts = ref<any[]>([])
const loading = ref(false)
const currentPage = ref(1)
const totalPages = ref(0)

async function fetchDrafts() {
  loading.value = true
  try {
    const res = await request.get(`/article/drafts?page=${currentPage.value}&size=10`)
    console.log('草稿列表:', res)
    if (res.code === 200 && res.data) {
      drafts.value = res.data.records || []
      totalPages.value = res.data.pages || 0
    }
  } catch (error) {
    console.error('获取草稿失败:', error)
  } finally {
    loading.value = false
  }
}

function changePage(page: number) {
  currentPage.value = page
  fetchDrafts()
  window.scrollTo(0, 0)
}

function editDraft(articleId: string) {
  router.push(`/edit-article?id=${articleId}`)
}

async function publishDraft(articleId: string) {
  if (!confirm('确定要发布这篇文章吗？')) return
  
  try {
    const res = await request.post(`/article/${articleId}/publish`)
    if (res.code === 200) {
      alert('发布成功')
      fetchDrafts()
    } else {
      alert(res.message || '发布失败')
    }
  } catch (error) {
    console.error('发布失败:', error)
    alert('发布失败')
  }
}

async function deleteDraft(articleId: string) {
  if (!confirm('确定要删除这篇草稿吗？')) return
  
  try {
    const res = await request.delete(`/article/${articleId}`)
    if (res.code === 200) {
      alert('删除成功')
      fetchDrafts()
    } else {
      alert(res.message || '删除失败')
    }
  } catch (error) {
    console.error('删除失败:', error)
    alert('删除失败')
  }
}

function getImageUrl(url: string | undefined): string {
  if (!url) return '/images/default-cover.jpg'
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
  
  // 原图也加载失败，显示默认封面
  target.src = '/images/default-cover.jpg'
}

// 去除HTML标签
function stripHtmlTags(str: string): string {
  if (!str) return ''
  return str.replace(/<[^>]*>/g, '')
}

function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

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
  fetchDrafts()
})

onUnmounted(() => {
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
})
</script>

<style scoped>
.draft-box-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
}

.draft-box-page::before {
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
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 50px;
  z-index: 1000;
}

.nav-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 22px;
  font-weight: bold;
  color: #4facfe;
  cursor: pointer;
}

.logo-icon {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  fill: #4facfe;
}

.logo-text {
  display: inline;
}

.page-title {
  font-size: 16px;
  color: #666;
  margin-left: 16px;
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
  background: rgba(0, 0, 0, 0.05);
}

.container {
  max-width: 900px;
  margin: 100px auto 50px;
  padding: 0 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
}

.page-header h1 {
  color: #333;
  font-size: 28px;
}

.draft-count {
  color: rgba(0, 0, 0, 0.5);
  font-size: 14px;
}

.loading-state,
.empty-state {
  text-align: center;
  padding: 80px 20px;
  color: #666;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 20px;
}

.empty-icon {
  width: 60px;
  height: 60px;
  margin: 0 auto 20px;
  color: #ccc;
}

.empty-icon svg {
  width: 100%;
  height: 100%;
}

.create-btn {
  margin-top: 20px;
  padding: 12px 30px;
  background: white;
  color: #333;
  border: 1px solid #ddd;
  border-radius: 20px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
}

.create-btn:hover {
  border-color: #999;
  background: #f5f5f5;
}

.draft-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.draft-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 16px;
  overflow: hidden;
  display: flex;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
  transition: all 0.3s;
}

.draft-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 30px rgba(102, 126, 234, 0.2);
}

.draft-cover {
  width: 200px;
  height: 130px;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}

.draft-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  position: absolute;
  top: 0;
  left: 0;
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
  background: #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
}

.draft-content {
  flex: 1;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.draft-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  margin-bottom: 10px;
}

.draft-summary {
  font-size: 14px;
  color: #666;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.draft-meta {
  font-size: 12px;
  color: #999;
  margin-top: 10px;
}

.draft-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px;
  justify-content: center;
}

.action-btn {
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s;
  background: white;
}

.action-btn.edit {
  border: 1px solid #666;
  color: #666;
}

.action-btn.edit:hover {
  background: #666;
  color: white;
}

.action-btn.publish {
  border: 1px solid #52c41a;
  color: #52c41a;
}

.action-btn.publish:hover {
  background: #52c41a;
  color: white;
}

.action-btn.delete {
  border: 1px solid #ff4d4f;
  color: #ff4d4f;
}

.action-btn.delete:hover {
  background: #ff4d4f;
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
  border-color: #333;
  color: #333;
  background: #fafafa;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  color: #333;
  font-size: 14px;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 12px;
    height: 55px;
  }
  
  .logo {
    font-size: 18px;
    flex-shrink: 0;
  }
  
  .nav-right {
    gap: 6px;
    flex-shrink: 0;
  }
  
  .nav-btn {
    padding: 6px 10px;
    font-size: 12px;
    white-space: nowrap;
  }
  
  .container {
    margin-top: 70px;
    padding: 15px;
  }
  
  .page-header {
    margin-bottom: 20px;
  }
  
  .page-header h1 {
    font-size: 22px;
  }
  
  .draft-count {
    font-size: 13px;
  }
  
  .draft-list {
    gap: 15px;
  }
  
  .draft-card {
    padding: 15px;
    flex-direction: column;
  }
  
  .draft-cover {
    width: 100%;
    height: 150px;
    margin-bottom: 12px;
  }
  
  .draft-info {
    width: 100%;
  }
  
  .draft-title {
    font-size: 16px;
  }
  
  .draft-preview {
    font-size: 13px;
  }
  
  .action-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
}

@media (max-width: 480px) {
  .navbar {
    padding: 0 10px;
    height: 50px;
  }
  
  .logo {
    font-size: 16px;
  }
  
  .logo-icon {
    width: 28px;
    height: 28px;
  }
  
  .logo-text {
    display: none;
  }
  
  .nav-right {
    gap: 4px;
  }
  
  .nav-btn {
    padding: 5px 8px;
    font-size: 11px;
  }
  
  .container {
    margin-top: 60px;
    padding: 12px 10px;
  }
  
  .page-header {
    margin-bottom: 15px;
  }
  
  .page-header h1 {
    font-size: 20px;
  }
  
  .draft-count {
    font-size: 12px;
  }
  
  .draft-list {
    gap: 12px;
  }
  
  .draft-card {
    padding: 12px;
    border-radius: 10px;
  }
  
  .draft-cover {
    height: 130px;
    border-radius: 8px;
  }
  
  .draft-title {
    font-size: 15px;
    margin-bottom: 8px;
  }
  
  .draft-preview {
    font-size: 12px;
    margin-bottom: 10px;
  }
  
  .draft-meta {
    flex-direction: column;
    gap: 10px;
  }
  
  .draft-time {
    font-size: 11px;
  }
  
  .draft-actions {
    width: 100%;
    justify-content: flex-end;
  }
  
  .action-btn {
    padding: 5px 10px;
    font-size: 11px;
  }
  
  .pagination {
    gap: 10px;
    margin-top: 20px;
  }
  
  .page-btn {
    padding: 8px 14px;
    font-size: 12px;
  }
}
</style>
