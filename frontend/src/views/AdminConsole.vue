<template>
  <div class="admin-console">
    <header class="admin-header">
      <RouterLink to="/" class="admin-brand"><span>e</span> EasyJob <small>管理后台</small></RouterLink>
      <div class="admin-header-right"><span v-if="operator">{{ operator.nickName }}</span><RouterLink to="/">返回社区 ↗</RouterLink></div>
    </header>
    <ContentState v-if="authorizing" kind="loading" title="正在验证管理权限" />
    <section v-else-if="accessError" class="admin-denied"><ContentState kind="error" title="暂时无法进入管理后台" :description="accessError" @retry="authorize" /><RouterLink to="/">返回社区</RouterLink></section>
    <div v-else class="admin-layout">
      <aside class="admin-sidebar">
        <p>工作台</p>
        <button v-for="item in availableSections" :key="item.key" :class="{selected:section === item.key}" :aria-current="section === item.key ? 'page' : undefined" @click="changeSection(item.key)"><component :is="item.icon" />{{ item.title }}<span>↗</span></button>
        <div class="admin-sidebar-note"><span class="admin-dot"></span>后台权限已验证<p>每次操作由后端校验<br>变更记录可在日志查看</p></div>
      </aside>
      <main class="admin-main">
        <div class="admin-page-heading"><div><small>{{ section === 'overview' ? '工作台 / 概览' : `工作台 / ${currentSection.title}` }}</small><h1>{{ currentSection.title }}</h1><p>{{ currentSection.description }}</p></div><button class="admin-button" :disabled="loading || refreshing" @click="refresh">刷新 <Refresh /></button></div>
        <p v-if="overviewError" role="alert" class="admin-feedback">{{ overviewError }}</p>
        <template v-if="section === 'overview'">
          <div class="admin-metrics" :style="{ '--metric-columns': metricColumns }">
            <div v-for="metric in metrics" :key="metric.label" class="admin-metric"><span>{{ metric.label }}</span><strong>{{ overview ? metric.value : '—' }}</strong><small>{{ metric.note }}</small></div>
          </div>
          <AdminStatisticsPanel v-if="can('statistics.read')" ref="statisticsPanel" />
          <div class="admin-overview-panels">
            <section class="admin-panel"><div class="admin-panel-heading"><h2>阅读成长规则</h2><span class="admin-pill">永久累计</span></div><p>用户阅读解锁内容，达到累计时间后升级，已获得等级不衰减。</p><div v-for="rule in rules" :key="rule.level" class="admin-rule"><span>L{{ rule.level }}</span><strong>{{ rule.minSeconds === 0 ? '公开阅读' : readingDuration(rule.minSeconds) }}</strong></div></section>
            <section class="admin-panel admin-quick-start"><h2>内容管理</h2><p>在文章列表设置阅读门槛，或下架与恢复已发布内容。</p><button v-if="can('articles.read')" class="admin-button primary" @click="changeSection('articles')">管理文章 <ArrowRight /></button><div class="admin-policy"><strong>下架与草稿分开</strong><p>下架内容不会进入作者草稿箱。恢复后保留原发布时间与阅读等级。</p></div><div class="admin-policy"><strong>用户资料与成长管理</strong><p>编辑资料、角色与账号状态，按需校正阅读时长。每次修改均保留原因与操作记录。</p></div></section>
          </div>
        </template>
        <ArticleReviewPanel v-else-if="section==='reviews'" ref="reviewPanel" @changed="loadOverview" />
        <AdminOperationsPanel v-else-if="section==='operations'" ref="operationsPanel" />
        <AdminCategoriesPanel v-else-if="section==='categories'" ref="categoriesPanel" />
        <AdminAgentMetricsPanel v-else-if="section==='agentMetrics'" ref="agentMetricsPanel" />
        <section v-else class="admin-panel admin-list-panel">
          <form v-if="section !== 'logs'" class="admin-filters" @submit.prevent="search">
            <label class="admin-search"><Search /><input v-model="keyword" maxlength="80" :placeholder="section === 'articles' ? '搜索文章标题、作者' : '搜索昵称、用户 ID'" :aria-label="section === 'articles' ? '搜索文章标题、作者' : '搜索昵称、用户 ID'"></label>
            <select v-if="section === 'articles'" v-model="status" aria-label="文章状态"><option value="">全部状态</option><option value="1">已发布</option><option value="2">已下架</option></select>
            <button class="admin-button primary" type="submit">查询</button>
          </form>
          <ContentState v-if="loading" kind="loading" title="正在加载列表" />
          <ContentState v-else-if="error" kind="error" title="列表暂时无法加载" :description="error" @retry="loadRecords" />
          <ContentState v-else-if="!records.length" kind="empty" title="暂无匹配记录" />
          <div v-else class="admin-table-wrap">
            <table v-if="section === 'articles'" class="admin-table"><thead><tr><th>文章 / 作者</th><th>状态</th><th>阅读门槛</th><th>阅读量</th><th>更新于</th><th>操作</th></tr></thead><tbody><tr v-for="row in records" :key="row.articleId"><td class="admin-title-cell"><strong>{{ row.title }}</strong><small>{{ row.authorName || '作者已删除' }} · {{ row.articleId }}</small></td><td><span class="admin-pill" :class="{removed:row.status===2}">{{ articleStatus(row.status) }}</span></td><td><div class="admin-inline-editor"><select v-model.number="row.selectedLevel" :disabled="!!busy" :aria-label="`${row.title}的阅读等级`"><option v-for="rule in rules" :key="rule.level" :value="rule.level">L{{ rule.level }}{{ rule.level===0?' · 公开':'' }}</option></select><button class="admin-text-button" :disabled="!!busy || row.selectedLevel===row.requiredLevel" @click="saveLevel(row)">保存</button></div></td><td>{{ row.viewCount || 0 }}</td><td class="admin-time">{{ time(row.updateTime) }}</td><td><div class="admin-row-actions"><RouterLink v-if="row.status===1" :to="`/article/${row.articleId}`" target="_blank">查看 ↗</RouterLink><button v-if="row.status===1 || row.status===2" class="admin-text-button" :class="{danger:row.status===1}" :disabled="!!busy" @click="setVisibility(row)">{{ busy===row.articleId ? '处理中…' : row.status===1?'下架':'恢复' }}</button><span v-else class="admin-muted">由作者发布</span></div></td></tr></tbody></table>
            <table v-else-if="section === 'users'" class="admin-table"><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>阅读等级</th><th>累计有效阅读</th><th>注册于</th><th>操作</th></tr></thead><tbody><tr v-for="row in records" :key="row.userId"><td class="admin-title-cell"><RouterLink :to="`/user-space/${row.userId}`" target="_blank">{{ row.nickName }} ↗</RouterLink><small>{{ row.userId }}</small></td><td>{{ roleName(row.role) }}</td><td>{{ row.status===1?'正常':'已禁用' }}</td><td><span class="admin-pill">L{{ row.readingLevel }}</span></td><td>{{ readingDuration(row.readingSeconds) }}</td><td class="admin-time">{{ time(row.joinTime) }}</td><td><button class="admin-text-button" @click="editUser(row)">编辑</button></td></tr></tbody></table>
            <table v-else class="admin-table"><thead><tr><th>操作时间</th><th>管理员</th><th>操作</th><th>目标 ID</th><th>变更</th></tr></thead><tbody><tr v-for="row in records" :key="row.id"><td class="admin-time">{{ time(row.createdAt) }}</td><td>{{ row.adminName || row.adminUserId }}</td><td>{{ logLabel(row.action) }}</td><td>{{ row.targetId }}</td><td>{{ logChange(row) }}<small v-if="row.reason" class="admin-log-reason">原因：{{ row.reason }}</small><details v-if="row.detailsJson" class="admin-log-details"><summary>完整变更</summary><pre>{{ formatDetails(row.detailsJson) }}</pre></details></td></tr></tbody></table>
          </div>
          <div class="admin-pagination"><span>共 {{ total }} 条</span><div><button class="admin-button" :disabled="loading || page<=1" @click="turnPage(-1)">上一页</button><span>{{ page }} / {{ Math.max(1,pages) }}</span><button class="admin-button" :disabled="loading || page>=pages" @click="turnPage(1)">下一页</button></div></div>
        </section>
      </main>
    </div>
    <AdminUserEditor v-model="editingUser" :user-id="editingUserId" :operator-id="operator?.userId" @changed="userChanged" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataAnalysis, Document, User, Tickets, Refresh, Search, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ContentState from '@/components/ContentState.vue'
import ArticleReviewPanel from '@/components/ArticleReviewPanel.vue'
import AdminOperationsPanel from '@/components/AdminOperationsPanel.vue'
import AdminUserEditor from '@/components/AdminUserEditor.vue'
import AdminStatisticsPanel from '@/components/AdminStatisticsPanel.vue'
import AdminCategoriesPanel from '@/components/AdminCategoriesPanel.vue'
import AdminAgentMetricsPanel from '@/components/AdminAgentMetricsPanel.vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
import { readingDuration } from '@/utils/readingGrowth'

type Section = 'overview'|'articles'|'users'|'logs'|'reviews'|'operations'|'categories'|'agentMetrics'
type Row = { articleId:string;title:string;authorName:string;status:number;requiredLevel:number;selectedLevel:number;viewCount:number;updateTime:string;userId:string;nickName:string;role:number;readingLevel:number;readingSeconds:number;joinTime:string;id:string;action:string;adminName:string;adminUserId:string;targetId:string;beforeValue:string;afterValue:string;createdAt:string;reason?:string;detailsJson?:string }
type Overview = { users:number;published:number;restricted:number;removed:number;readingSeconds:number;pendingReviews:number;rules:{level:number;minSeconds:number}[] }
const router=useRouter(),route=useRoute()
const sections=[
  {key:'overview' as Section,title:'概览',description:'社区内容与阅读成长，一眼掌握。',icon:DataAnalysis},
  {key:'reviews' as Section,title:'文章审核',description:'查看完整提交版本，通过后更新公开内容。',icon:Tickets},
  {key:'articles' as Section,title:'文章管理',description:'调整阅读门槛，管理已发布内容的可见状态。',icon:Document},
  {key:'categories' as Section,title:'分类管理',description:'添加文章分类，组织社区内容与创作选项。',icon:Document},
  {key:'users' as Section,title:'用户与成长',description:'管理用户资料、角色、账号状态与阅读成长。',icon:User},
  {key:'operations' as Section,title:'运行与任务',description:'检查后台积压、失败任务和索引同步状态。',icon:DataAnalysis},
  {key:'agentMetrics' as Section,title:'Agent 指标',description:'查看运行结果、活跃时长及供应商实际返回的 Token 使用量。',icon:DataAnalysis},
  {key:'logs' as Section,title:'操作日志',description:'查看用户与内容变更、任务重试及索引对账记录。',icon:Tickets}
]
const section=ref<Section>(sections.some(s=>s.key===route.query.section)?route.query.section as Section:'overview')
const currentSection=computed(()=>sections.find(s=>s.key===section.value)!)
const operator=ref<{userId:string;nickName:string;permissions:string[]}>(),authorizing=ref(true),accessError=ref('')
const sectionPermission:Record<Section,string>={overview:'overview.read',articles:'articles.read',reviews:'reviews.read',users:'users.read',categories:'categories.read',operations:'operations.read',logs:'logs.read',agentMetrics:'metrics.read'}
const can=(permission:string)=>operator.value?.permissions?.includes(permission) || false
const availableSections=computed(()=>sections.filter(s=>can(sectionPermission[s.key])))
const roleName=(role:number)=>({1:'普通用户',2:'管理员',3:'审核员',4:'运营员'}[role] || '未知角色')
const overview=ref<Overview>(),overviewError=ref(''),refreshing=ref(false)
const rules=computed(()=>overview.value?.rules || [])
const metrics=computed(()=>[
  {label:'待审核版本',value:overview.value?.pendingReviews,note:'等待管理员处理的文章版本'},
  {label:'社区用户',value:overview.value?.users,note:'所有已注册账号'},
  {label:'已发布文章',value:overview.value?.published,note:'当前可公开发现的文章'},
  {label:'等级文章',value:overview.value?.restricted,note:'已发布且设置了阅读门槛'},
  {label:'已下架文章',value:overview.value?.removed,note:'可恢复，独立于草稿'},
  {label:'累计有效阅读',value:readingDuration(overview.value?.readingSeconds || 0),note:'所有用户累计阅读时长'}
])
// 指标超过 4 个时平均排成两行，避免最后一行只剩一张卡片
const metricColumns=computed(()=>metrics.value.length>4?Math.ceil(metrics.value.length/2):metrics.value.length)
const keyword=ref(''),status=ref(''),page=ref(1),pages=ref(0),total=ref(0),records=ref<Row[]>([])
const loading=ref(false),error=ref(''),busy=ref('')
const editingUser=ref(false),editingUserId=ref('')
function editUser(row:Row){editingUserId.value=row.userId;editingUser.value=true}
async function userChanged(){await refresh();try{const result:any=await request.get('/admin/me');if(!disposed)operator.value=result.data}catch(e){ElMessage.error(message(e))}}
const formatDetails=(value:string)=>{try{return JSON.stringify(typeof value==='string'?JSON.parse(value):value,null,2)}catch{return value}}
const gate=latestRequest();let disposed=false
const reviewPanel=ref<{reload:()=>Promise<void>}>()
const statisticsPanel=ref<{reload:()=>Promise<void>}>()
const operationsPanel=ref<{reload:()=>Promise<void>}>()
const categoriesPanel=ref<{reload:()=>Promise<void>}>()
const agentMetricsPanel=ref<{reload:()=>Promise<void>}>()
const message=(error:unknown)=>error instanceof Error?error.message:'请求失败，请稍后重试'
const articleStatus=(status:number)=>({0:'草稿',1:'已发布',2:'已下架'}[status] || '其他状态')
const logLabel=(action:string)=>({category_create:'新增文章分类',category_update:'修改文章分类',category_migrate:'迁移文章分类',user_update:'修改用户资料',reading_level:'设置阅读等级',visibility:'调整文章状态',task_retry:'重试后台任务',index_reconcile:'安排索引对账'}[action] || action)
const logChange=(row:Row)=>row.action==='category_create'?`新增：${row.afterValue}`:row.action==='reading_level'?`L${row.beforeValue} → L${row.afterValue}`:row.action==='visibility'?`${articleStatus(Number(row.beforeValue))} → ${articleStatus(Number(row.afterValue))}`:`${row.beforeValue} → ${row.afterValue}`
const time=(value:string)=>value?value.replace('T',' ').slice(0,16):'—'
async function authorize(){
  authorizing.value=true;accessError.value=''
  try{const result:any=await request.get('/admin/me');if(disposed)return;operator.value=result.data;if(!can(sectionPermission[section.value])){section.value='overview';await router.replace('/admin')}await refresh()}
  catch(err){if(!disposed)accessError.value=message(err)}finally{if(!disposed)authorizing.value=false}
}
async function loadOverview(){
  try{const result:any=await request.get('/admin/overview');if(!disposed){overview.value=result.data;overviewError.value=''}}
  catch(err){if(!disposed)overviewError.value=message(err)}
}
async function loadRecords(){
  if(section.value==='overview')return
  if(section.value==='reviews'){await reviewPanel.value?.reload();return}
  if(section.value==='operations'){await operationsPanel.value?.reload();return}
  if(section.value==='categories'){await categoriesPanel.value?.reload();return}
  if(section.value==='agentMetrics'){await agentMetricsPanel.value?.reload();return}
  const run=gate.begin();loading.value=true;error.value=''
  try{
    const result:any=await request.get(`/admin/${section.value}`,{params:{keyword:keyword.value.trim(),page:page.value,size:20,...(section.value==='articles' && status.value!==''?{status:Number(status.value)}:{})},signal:run.signal})
    if(!run.isCurrent() || disposed)return
    records.value=result.data.records.map((row:Row)=>({...row,selectedLevel:row.requiredLevel}));total.value=result.data.total;pages.value=result.data.pages
  }catch(err){if(run.isCurrent() && !disposed)error.value=message(err)}finally{if(run.isCurrent() && !disposed)loading.value=false}
}
async function refresh(){refreshing.value=true;await Promise.all([loadOverview(),loadRecords(),statisticsPanel.value?.reload()]);if(!disposed)refreshing.value=false}
function changeSection(next:Section){if(!can(sectionPermission[next]))return;gate.cancel();section.value=next;keyword.value='';status.value='';page.value=1;records.value=[];total.value=0;pages.value=0;error.value='';loading.value=false;void router.replace({path:'/admin',query:next==='overview'?{}:{section:next}});void loadRecords()}
function search(){page.value=1;void loadRecords()}
function turnPage(delta:number){page.value+=delta;void loadRecords()}
async function saveLevel(row:Row){
  busy.value=row.articleId
  try{await request.put(`/admin/articles/${row.articleId}/reading-level`,{expectedLevel:row.requiredLevel,level:row.selectedLevel});ElMessage.success('阅读等级已保存');await refresh()}
  catch(err){ElMessage.error(message(err));await loadRecords()}finally{busy.value=''}
}
async function setVisibility(row:Row){
  const removing=row.status===1
  try{await ElMessageBox.confirm(removing?`下架《${row.title}》后，社区中将无法阅读，文章不会进入草稿箱。`:`恢复《${row.title}》后，将按原有阅读等级重新提供访问。`,removing?'下架文章':'恢复文章',{confirmButtonText:removing?'确认下架':'确认恢复',cancelButtonText:'取消',type:'warning'})}catch{return}
  busy.value=row.articleId
  try{await request.put(`/admin/articles/${row.articleId}/visibility`,{expectedStatus:row.status,status:removing?2:1});ElMessage.success(removing?'文章已下架':'文章已恢复');await refresh()}
  catch(err){ElMessage.error(message(err));await loadRecords()}finally{busy.value=''}
}
onMounted(authorize)
onUnmounted(()=>{disposed=true;gate.cancel()})
</script>

<style scoped>
.admin-log-reason{display:block;margin-top:8px;color:var(--ej-muted);font-size:11px;overflow-wrap:anywhere}.admin-log-details{margin-top:8px;font-size:11px}.admin-log-details summary{cursor:pointer}.admin-log-details pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:500px;max-height:300px;overflow:auto;padding:12px;background:var(--ej-canvas);border-radius:8px}
.admin-console{min-height:100vh;background:var(--ej-canvas);color:var(--ej-ink);font-family:var(--ej-font)}
.admin-header{height:76px;border-bottom:1px solid var(--ej-line);display:flex;align-items:center;justify-content:space-between;padding:0 36px;background:var(--ej-surface);gap:20px}
.admin-brand{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:800;text-decoration:none;color:inherit;white-space:nowrap}.admin-brand>span{background:var(--ej-ink);color:var(--ej-surface);border-radius:50%;width:36px;height:36px;display:grid;place-items:center;font-style:italic}.admin-brand small{font-size:12px;font-weight:500;color:var(--ej-muted);border-left:1px solid var(--ej-line);margin-left:8px;padding-left:18px}
.admin-header-right{display:flex;align-items:center;gap:20px;font-size:13px}.admin-header-right>a{border:1px solid var(--ej-ink);border-radius:99px;padding:10px 16px;text-decoration:none;color:inherit}
.admin-layout{display:grid;grid-template-columns:224px minmax(0,1fr);max-width:1600px;margin:auto;min-height:calc(100vh - 76px)}
.admin-sidebar{padding:30px 20px;border-right:1px solid var(--ej-line)}.admin-sidebar>p{font-size:11px;color:var(--ej-muted);padding:0 12px;letter-spacing:2px;margin:0 0 18px}.admin-sidebar>button{display:flex;align-items:center;gap:10px;width:100%;background:transparent;border:1px solid transparent;border-radius:12px;padding:13px 12px;margin-bottom:8px;font-size:14px;cursor:pointer;transition:background .18s,transform .18s}.admin-sidebar>button:hover{background:var(--ej-surface);transform:translateX(2px)}.admin-sidebar>button.selected{background:var(--studio-lime);border-color:var(--ej-ink)}.admin-sidebar svg{width:18px;height:18px}.admin-sidebar button>span{margin-left:auto}.admin-sidebar-note{margin:48px 12px 0;font-size:11px;color:var(--ej-muted);line-height:1.8}.admin-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#608e32;margin-right:7px}.admin-sidebar-note p{margin:8px 0}
.admin-main{padding:36px;min-width:0}.admin-page-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:30px}.admin-page-heading small{font-size:11px;color:var(--ej-muted)}.admin-page-heading h1{font-size:28px;letter-spacing:-1px;margin:10px 0}.admin-page-heading p{font-size:13px;color:var(--ej-muted);margin:0;line-height:1.8}
.admin-button{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 16px;border:1px solid var(--ej-ink);border-radius:99px;background:var(--ej-surface);color:var(--ej-ink);font-size:12px;white-space:nowrap;cursor:pointer;transition:transform .18s,box-shadow .18s}.admin-button:hover:enabled{transform:translateY(-2px);box-shadow:var(--ej-shadow)}.admin-button.primary{background:var(--ej-ink);color:var(--ej-surface)}.admin-button:disabled,.admin-text-button:disabled{opacity:.4;cursor:not-allowed}.admin-button svg{width:15px;height:15px}
.admin-metrics{display:grid;grid-template-columns:repeat(var(--metric-columns,3),minmax(0,1fr));gap:14px}.admin-metric{border:1px solid var(--ej-ink);border-radius:16px;padding:20px;background:var(--ej-surface);box-shadow:var(--ej-shadow)}.admin-metric span{font-size:12px;color:var(--ej-muted)}.admin-metric strong{display:block;font-size:28px;margin:16px 0;line-height:1.3;overflow-wrap:anywhere}.admin-metric small{font-size:10px;color:var(--ej-muted)}
.admin-overview-panels{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:28px}.admin-panel{background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:18px;padding:24px}.admin-panel h2{font-size:17px;margin:0}.admin-panel p{font-size:12px;color:var(--ej-muted);line-height:1.8}.admin-panel-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.admin-rule{display:flex;justify-content:space-between;padding:15px 0;border-bottom:1px solid var(--ej-hairline);font-size:13px}.admin-rule:last-child{border-bottom:0}.admin-rule>span{font-weight:700}.admin-rule strong{font-weight:500}.admin-pill{display:inline-block;padding:4px 8px;border-radius:99px;background:var(--studio-lime-soft);font-size:11px;white-space:nowrap}.admin-pill.removed{background:#f7ded5}.admin-policy{border-top:1px solid var(--ej-hairline);margin-top:24px;padding-top:20px;font-size:13px}.admin-policy p{margin-bottom:0}.admin-quick-start>.admin-button{margin-top:12px}
.admin-filters{display:flex;gap:12px;align-items:center;margin-bottom:22px;flex-wrap:wrap}.admin-search{display:flex;align-items:center;gap:10px;border:1px solid var(--ej-line);border-radius:99px;padding:10px 14px;min-width:220px;flex:1;max-width:480px}.admin-search svg{width:16px;height:16px;flex-shrink:0}.admin-search input{min-width:0;width:100%;border:0;background:transparent;font-size:13px;outline:none}select{border:1px solid var(--ej-line);border-radius:10px;padding:8px 10px;background:var(--ej-surface);font-size:12px;color:inherit}
.admin-table-wrap{overflow-x:auto}.admin-table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}.admin-table th{font-weight:500;color:var(--ej-muted);background:var(--ej-canvas);white-space:nowrap}.admin-table th,.admin-table td{padding:16px 12px;border-bottom:1px solid var(--ej-hairline)}.admin-table tr:hover td{background:#f2efe744}.admin-title-cell{min-width:180px;max-width:320px}.admin-title-cell strong,.admin-title-cell>a{display:block;font-weight:600;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.admin-title-cell small{display:block;font-size:10px;color:var(--ej-muted);margin-top:6px}.admin-table a{color:var(--ej-ink);text-decoration:none}.admin-table a:hover{text-decoration:underline}.admin-inline-editor{display:flex;align-items:center;gap:8px}.admin-inline-editor select{width:92px}.admin-text-button{padding:4px 0;color:var(--ej-ink);background:transparent;border:0;white-space:nowrap;font:inherit;cursor:pointer}.admin-text-button:hover:enabled{text-decoration:underline}.admin-text-button.danger{color:#b44a36}.admin-row-actions{display:flex;align-items:center;gap:14px;white-space:nowrap}.admin-muted,.admin-time{color:var(--ej-muted);white-space:nowrap}.admin-pagination{display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--ej-hairline);margin-top:24px;padding-top:18px;font-size:12px;color:var(--ej-muted);gap:12px}.admin-pagination>div{display:flex;align-items:center;gap:14px}.admin-feedback{color:#b44a36;font-size:12px}.admin-denied{max-width:700px;margin:70px auto;text-align:center}.admin-denied>a{color:inherit}
@media(max-width:1200px){.admin-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.admin-main{padding:28px 22px}.admin-layout{grid-template-columns:190px minmax(0,1fr)}}
@media(max-width:760px){.admin-header{height:64px;padding:0 16px}.admin-brand{font-size:18px}.admin-brand small{display:none}.admin-header-right{gap:10px}.admin-layout{display:block}.admin-sidebar{padding:14px;border-right:0;border-bottom:1px solid var(--ej-line);display:flex;gap:6px;overflow-x:auto}.admin-sidebar>p,.admin-sidebar-note{display:none}.admin-sidebar>button{white-space:nowrap;flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:10px}.admin-sidebar button>span{display:none}.admin-main{padding:24px 16px}.admin-page-heading h1{font-size:24px}.admin-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.admin-metric{padding:16px}.admin-metric strong{font-size:23px}.admin-overview-panels{grid-template-columns:1fr}.admin-panel{padding:18px}.admin-search{min-width:0;max-width:none;flex-basis:100%}.admin-pagination{flex-wrap:wrap}.admin-table td,.admin-table th{padding:14px 10px}}
@media(prefers-reduced-motion:reduce){.admin-sidebar>button,.admin-button{transition:none}}
</style>
