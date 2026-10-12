<template>
  <div class="draft-box-page">
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
        <span class="page-title">草稿与审核</span>
      </div>
      <AppNavigation />
    </nav>

    <div class="container">
      <div class="page-header">
        <div><h1>草稿与审核</h1><p class="page-description">继续创作，或查看文章的审核进度。审核通过后才会公开。</p></div>
        <span v-if="!loading && !loadError" class="draft-count">{{ revisionFilter ? `${revisionLabel(Number(revisionFilter))} · ${total} 个版本` : `共 ${total} 个创作版本` }}</span>
      </div>
      <div class="revision-filters" role="group" aria-label="按审核状态筛选"><button v-for="tab in revisionTabs" :key="tab.value" :class="{active:revisionFilter===tab.value}" :aria-pressed="revisionFilter===tab.value" @click="revisionFilter=tab.value;currentPage=1;fetchDrafts()">{{ tab.label }}</button></div>

      <ContentState v-if="loading" kind="loading" title="正在加载草稿" />
      <ContentState v-else-if="loadError" kind="error" title="草稿暂时无法加载" :description="loadError" @retry="fetchDrafts" />
      
      <div v-else-if="drafts.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/>
          </svg>
        </div>
        <p>{{ revisionFilter ? `暂无${revisionLabel(Number(revisionFilter))}版本` : '还没有创作版本' }}</p>
        <span class="empty-description">{{ revisionFilter ? '切换筛选，查看其他草稿与审核进度。' : '把一个想法写下来，保存草稿后随时继续。' }}</span>
        <div class="empty-actions">
          <button v-if="revisionFilter" class="draft-button secondary" @click="revisionFilter='';currentPage=1;fetchDrafts()">查看全部</button>
          <button class="draft-button primary" @click="$router.push('/create-article')">开始创作 <span aria-hidden="true">↗</span></button>
        </div>
      </div>

      <div v-else class="draft-list">
        <article
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
            <div v-else class="draft-placeholder" aria-hidden="true">
              <span class="placeholder-label">WORK IN PROGRESS</span>
              <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 6h15l9 9v27H13zM28 6v10h9M19 24h12M19 30h12M19 36h7"/></svg>
              <span class="placeholder-version">{{ draft.version ? `VERSION ${String(draft.version).padStart(2, '0')}` : 'DRAFT' }}</span>
            </div>
          </div>
          <div class="draft-content">
            <div class="revision-label">
              <span class="revision-badge" :class="`state-${draft.revisionState}`">{{ revisionLabel(draft.revisionState) }}</span>
              <span v-if="draft.version">V{{ draft.version }}</span>
              <span v-if="draft.articleStatus===1" class="public-version">旧版继续公开</span>
            </div>
            <h3 class="draft-title">{{ draft.title || '无标题' }}</h3>
            <p class="draft-summary">{{ stripHtmlTags(draft.summary || '还没有摘要，继续编辑来完善这篇文章。') }}</p>
            <p v-if="draft.reviewReason && draft.revisionState===3" class="revision-reason"><strong>审核意见</strong>{{ draft.reviewReason }}</p>
            <div class="draft-footer">
              <span class="draft-meta">最后编辑 {{ formatDate(draft.updateTime || draft.createTime) }}</span>
              <div class="draft-actions">
                <button v-if="draft.revisionState!==1" class="draft-button primary" :disabled="busyIds.has(draft.articleId)" @click="editDraft(draft.articleId)">继续编辑 <span aria-hidden="true">↗</span></button>
                <button v-if="draft.revisionState!==1" class="draft-button secondary" :disabled="busyIds.has(draft.articleId)" @click="publishDraft(draft)">提交审核</button>
                <button v-else class="draft-button secondary" :disabled="busyIds.has(draft.articleId)" @click="withdraw(draft)">撤回审核</button>
                <button class="draft-button quiet" :disabled="busyIds.has(draft.articleId)" @click="historyArticle=draft;showHistory=true">版本历史</button>
                <button v-if="draft.revisionState!==1" class="draft-button quiet danger" :disabled="busyIds.has(draft.articleId)" @click="draft.articleStatus===1?discard(draft):deleteDraft(draft.articleId)">{{ draft.articleStatus===1?'丢弃修改':'删除' }}</button>
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- 分页 -->
      <div v-if="!loading && !loadError && drafts.length > 0" class="pagination">
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
    <ArticleRevisionHistory v-if="historyArticle" v-model="showHistory" :article-id="historyArticle.articleId" :revision-id="historyArticle.revisionId" :lock-version="historyArticle.lockVersion" :initial-revision-id="historyArticle.initialRevisionId" :pending="historyArticle.revisionState===1" @restored="fetchDrafts" />

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
import AppNavigation from '@/components/AppNavigation.vue'
import ArticleRevisionHistory from '@/components/ArticleRevisionHistory.vue'
import ContentState from '@/components/ContentState.vue'
import { notify, confirmAction, errorMessage } from '@/utils/feedback'
import { latestRequest } from '@/utils/latestRequest'
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter,useRoute } from 'vue-router'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { getThumbUrl } from '../utils/image'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'

const router = useRouter()
const route=useRoute(),notificationRequest=latestRequest()
const drafts = ref<any[]>([])
const loading = ref(false)
const loadError = ref('')
const total = ref(0)
const busyIds = ref(new Set<string>())
const requests = latestRequest()
const currentPage = ref(1)
const totalPages = ref(0)
const revisionFilter=ref('')
const revisionTabs=[{value:'',label:'全部'},{value:'0',label:'草稿'},{value:'1',label:'待审核'},{value:'3',label:'已驳回'},{value:'4',label:'已撤回'}]
const revisionLabel=(value:number)=>({0:'草稿',1:'待审核',3:'已驳回',4:'已撤回'}[value] || '草稿')
const historyArticle=ref<any>(),showHistory=ref(false)
watch(()=>[route.query.articleId,route.query.revisionId],async()=>{
  const ticket=notificationRequest.begin()
  showHistory.value=false
  const aid=route.query.articleId,rid=route.query.revisionId
  if(typeof aid!=='string' || !/^\d+$/.test(aid))return
  if(rid!==undefined && (typeof rid!=='string' || !/^\d+$/.test(rid)))return
  try {
    const result:any=await request.get(`/article/${aid}/edit`,{signal:ticket.signal})
    if(!ticket.isCurrent())return
    historyArticle.value={...result.data,articleId:aid,initialRevisionId:rid}
    showHistory.value=true
  }catch(e){if(ticket.isCurrent())notify.error(errorMessage(e,'该文章已删除或暂时无法查看审核结果'))}
},{immediate:true})
onUnmounted(()=>notificationRequest.cancel())

async function fetchDrafts() {
  const ticket = requests.begin()
  loadError.value = ''
  loading.value = true
  try {
    const res = await request.get('/article/work', { params:{page:currentPage.value,size:10,...(revisionFilter.value!==''?{state:Number(revisionFilter.value)}:{})},signal: ticket.signal })
    if (!ticket.isCurrent()) return
    if (res.code === 200 && res.data) {
      drafts.value = res.data.records || []
      totalPages.value = res.data.pages || 0
      total.value = res.data.total || 0
      if (currentPage.value > Math.max(1, totalPages.value)) {
        currentPage.value = Math.max(1, totalPages.value)
        await fetchDrafts()
      }
    } else throw new Error('草稿列表暂时不可用，请重新加载')
  } catch (error) {
    if (ticket.isCurrent()) loadError.value = errorMessage(error, '请检查网络后重试')
  } finally {
    if (ticket.isCurrent()) loading.value = false
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

async function publishDraft(draft: any) {
  const articleId=draft.articleId
  if (busyIds.value.has(articleId)) return
  busyIds.value.add(articleId)
  try {
    if (!await confirmAction(`将「${draft.title || '无标题'}」提交给管理员审核。${draft.articleStatus===1?'审核期间，当前公开版本保持不变；通过后更新正文。':'审核通过后，这篇文章才会公开。'}`, '提交审核', { confirmText:'提交审核' })) return
    const res = await request.post(`/article/${articleId}/publish`,{expectedRevisionId:draft.revisionId,expectedLockVersion:draft.lockVersion})
    if (res.code === 200) {
      notify.success('已提交审核')
      await fetchDrafts()
    }
  } catch (error) {
    notify.error(errorMessage(error, '提交审核失败，请重试'))
  } finally {
    busyIds.value.delete(articleId)
  }
}
async function withdraw(draft:any){await revisionAction(draft,'withdraw','撤回后可以修改，该版本不再接受审核。','已撤回审核')}
async function discard(draft:any){await revisionAction(draft,'discard','丢弃这份修改草稿？公开版本保持不变，历史快照仍然保留。','已丢弃修改')}
async function revisionAction(draft:any,action:string,message:string,success:string){if(busyIds.value.has(draft.articleId))return;busyIds.value.add(draft.articleId);try{if(!await confirmAction(message,'确认操作'))return;await request.post(`/article/${draft.articleId}/revisions/${draft.revisionId}/${action}`);notify.success(success);await fetchDrafts()}catch(error){notify.error(errorMessage(error,'操作失败，请刷新后重试'))}finally{busyIds.value.delete(draft.articleId)}}

async function deleteDraft(articleId: string) {
  if (busyIds.value.has(articleId)) return
  busyIds.value.add(articleId)
  try {
    if (!await confirmAction('确定删除这篇草稿吗？删除后无法继续编辑。', '删除草稿', { confirmText:'删除草稿', type:'error' })) return
    const res = await request.delete(`/article/${articleId}`)
    if (res.code === 200) {
      notify.success('草稿已删除')
      await fetchDrafts()
    }
  } catch (error) {
    notify.error(errorMessage(error, '删除失败，请重试'))
  } finally {
    busyIds.value.delete(articleId)
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
  return new Date(dateStr).toLocaleString('zh-CN', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false })
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
  requests.cancel()
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
})
</script>

<style scoped>
.draft-box-page {
  display: flow-root;
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
  background: var(--ej-canvas);
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


#app .draft-box-page .container { margin: 110px auto 50px; padding: 0 24px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.page-header h1 { font-size: 28px; }
.page-description { color: var(--ej-muted); font-size: 13px; line-height: 1.8; margin-top: 8px; }
.draft-count { font-size: 13px; color: var(--ej-muted); white-space: nowrap; }
.revision-filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 26px; }
.revision-filters button { padding: 8px 18px; border: 1px solid var(--ej-line); border-radius: 999px; color: var(--ej-ink); background: transparent; font: inherit; font-size: 13px; cursor: pointer; transition: background 180ms, border-color 180ms; }
.revision-filters button:hover { background: var(--ej-surface); border-color: var(--ej-ink); }
.revision-filters button.active { background: var(--studio-lime); border-color: var(--ej-ink); }
.draft-list { display: flex; flex-direction: column; gap: 18px; }
#app .draft-box-page .draft-card { display: grid; grid-template-columns: 150px minmax(0, 1fr); align-items: start; gap: 24px; padding: 22px; overflow: hidden; }
.draft-cover { width: 150px; height: 130px; position: relative; overflow: hidden; border-radius: 12px; background: var(--ej-canvas); border: 1px solid var(--ej-line); }
.draft-cover img { width: 100%; height: 100%; object-fit: cover; }
.draft-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: space-between; height: 100%; padding: 14px 8px 12px; color: var(--ej-ink); background: linear-gradient(135deg, #eff4d6 0%, #eff4d6 65%, #e3e9cc 65%); }
.draft-placeholder svg { width: 42px; height: 42px; }
.placeholder-label { font-size: 8px; letter-spacing: 1px; }
.placeholder-version { font-size: 10px; letter-spacing: 1.3px; }
.draft-content { min-width: 0; }
.revision-label { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--ej-muted); margin-bottom: 10px; }
.revision-badge { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 9px; color: #56613f; background: #edf1e4; font-weight: 600; }
.revision-badge::before { content: ''; width: 5px; height: 5px; background: currentColor; border-radius: 50%; }
.revision-badge.state-1 { background: #fff0d1; color: #8b631a; }
.revision-badge.state-3 { background: #ffe4dc; color: #994735; }
.revision-badge.state-4 { background: #eeebe5; color: #706d64; }
.public-version { padding-left: 10px; border-left: 1px solid var(--ej-line); }
#app .draft-box-page .draft-title { font-size: 18px; line-height: 1.5; margin: 0 0 8px; overflow-wrap: anywhere; }
#app .draft-box-page .draft-summary { font-size: 13px; line-height: 1.8; color: var(--ej-muted); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; margin: 0; }
.revision-reason { display: flex; gap: 10px; padding: 10px 12px; margin-top: 12px; background: #fff1e9; border-left: 2px solid var(--studio-coral); border-radius: 0 8px 8px 0; font-size: 13px; line-height: 1.7; color: #8b4939; overflow-wrap: anywhere; }
.revision-reason strong { flex-shrink: 0; font-weight: 600; }
.draft-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px 20px; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--ej-line); }
.draft-meta { color: var(--ej-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.draft-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.draft-button { display: inline-flex; align-items: center; justify-content: center; gap: 12px; border: 1px solid transparent; border-radius: 999px; padding: 8px 14px; min-height: 36px; font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; color: var(--ej-ink); background: transparent; transition: background 180ms, box-shadow 200ms, border-color 180ms; }
.draft-button.primary { background: var(--ej-ink); color: var(--ej-surface); border-color: var(--ej-ink); }
.draft-button.secondary { border-color: var(--ej-line); }
.draft-button:not(:disabled):hover { background: var(--studio-lime); border-color: var(--ej-ink); color: var(--ej-ink); }
.draft-button.primary:not(:disabled):hover { box-shadow: 2px 2px 0 var(--ej-ink); }
.draft-button.quiet { color: var(--ej-muted); padding: 8px 10px; }
.draft-button.danger:not(:disabled):hover { color: #994735; background: #ffe4dc; border-color: transparent; }
.draft-button:disabled { opacity: .45; }
button:focus-visible { outline: 2px solid var(--ej-ink); outline-offset: 3px; }
.empty-state { text-align: center; padding: 70px 20px; color: var(--ej-muted); }
.empty-icon { width: 50px; height: 50px; margin: 0 auto 18px; opacity: .4; }
.empty-icon svg { width: 100%; height: 100%; }
.empty-description { display: block; font-size: 13px; margin-top: 10px; }
.empty-actions { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px; margin-top: 22px; }
.pagination { display: flex; justify-content: center; align-items: center; gap: 20px; margin-top: 30px; }
.page-btn { padding: 9px 22px; font-size: 13px; cursor: pointer; }
.page-info { color: var(--ej-muted); font-size: 12px; }
@media (max-width: 768px) {
  #app .draft-box-page .container { margin-top: 86px; padding: 0 16px; }
  .page-header { flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
  .page-header h1 { font-size: 24px; }
  .draft-count { font-size: 12px; }
  #app .draft-box-page .draft-card { grid-template-columns: 90px minmax(0, 1fr); padding: 18px; gap: 16px; }
  .draft-cover { width: 90px; height: 110px; }
  .placeholder-label { font-size: 7px; letter-spacing: 0; }
  #app .draft-box-page .draft-title { font-size: 16px; }
  .draft-footer { flex-direction: column; align-items: flex-start; }
  .draft-actions { gap: 6px; }
}
@media (max-width: 480px) {
  .page-description { font-size: 12px; }
  .revision-filters { gap: 6px; margin-bottom: 20px; }
  .revision-filters button { padding: 7px 13px; font-size: 12px; }
  #app .draft-box-page .draft-card { grid-template-columns: minmax(0, 1fr); padding: 18px; gap: 14px; }
  .draft-cover { width: 100%; height: 120px; }
  .draft-placeholder { flex-direction: row; padding: 18px; }
  .placeholder-label { font-size: 9px; letter-spacing: 1px; }
  .draft-placeholder svg { width: 46px; height: 46px; }
  .draft-actions { width: 100%; }
  .draft-button { padding: 8px 12px; }
  .revision-reason { flex-direction: column; gap: 4px; }
  .pagination { gap: 12px; }
  .page-btn { padding: 8px 15px; }
}
</style>
