<template>
  <section class="categories-panel">
    <div class="categories-toolbar"><p>支持一级与二级分类。新建分类默认启用。</p><button class="category-add" @click="creating=true">＋ 新增分类</button></div>
    <ContentState v-if="loading" kind="loading" title="正在加载分类" />
    <ContentState v-else-if="error" kind="error" title="分类暂时无法加载" :description="error" @retry="reload" />
    <ContentState v-else-if="!rows.length" kind="empty" title="暂无分类，添加第一个分类吧" />
    <div v-else class="category-table-wrap"><table><thead><tr><th>分类名称</th><th>所属分类</th><th>排序</th><th>说明</th><th>状态</th><th>文章数</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.categoryId"><td><strong>{{ row.categoryName }}</strong></td><td>{{ row.parentId==='0'?'一级分类':names.get(row.parentId) || '父分类不存在' }}</td><td>{{ row.sortOrder }}</td><td class="category-description">{{ row.description || '—' }}</td><td><span :class="{disabled:row.status!==1}">{{ row.status===1?'启用':'停用' }}</span></td><td>{{ row.articleCount || 0 }}</td><td><button class="category-row-action" @click="edit(row,'edit')">编辑</button><button v-if="!row.migratedTo" class="category-row-action" @click="edit(row,'move')">迁移文章</button><span v-else>已迁移</span></td></tr></tbody></table></div>
    <AdminCategoryCreator v-model="creating" @created="reload" />
    <AdminCategoryEditor v-model="editing" :row="selected" :rows="rows" :mode="mode" @changed="reload" />
  </section>
</template>
<script setup lang="ts">
import { computed,onMounted,onUnmounted,ref } from 'vue'
import AdminCategoryCreator from './AdminCategoryCreator.vue'
import AdminCategoryEditor from './AdminCategoryEditor.vue'
import type { CategoryRow } from '@/utils/categories'
import ContentState from './ContentState.vue'
import request from '@/utils/request'
import { latestRequest } from '@/utils/latestRequest'
const rows=ref<CategoryRow[]>([]),loading=ref(false),error=ref(''),creating=ref(false),gate=latestRequest()
const editing=ref(false),selected=ref<CategoryRow>(),mode=ref<'edit'|'move'>('edit')
function edit(row:CategoryRow,action:'edit'|'move'){selected.value=row;mode.value=action;editing.value=true}
let disposed=false
const names=computed(()=>new Map(rows.value.map(r=>[r.categoryId,r.categoryName])))
async function reload(){const run=gate.begin();loading.value=true;error.value='';try{const result:any=await request.get('/admin/categories',{signal:run.signal});if(run.isCurrent() && !disposed)rows.value=result.data}catch(e){if(run.isCurrent() && !disposed)error.value=e instanceof Error?e.message:'请求失败，请重试'}finally{if(run.isCurrent() && !disposed)loading.value=false}}
defineExpose({reload})
onMounted(reload);onUnmounted(()=>{disposed=true;gate.cancel()})
</script>
<style scoped>
.category-row-action{border:0;background:transparent;color:var(--ej-ink);font:inherit;cursor:pointer;padding:4px 8px;white-space:nowrap}.category-row-action:hover{text-decoration:underline}
.categories-panel{background:var(--ej-surface);border:1px solid var(--ej-line);border-radius:18px;padding:24px}.categories-toolbar{display:flex;gap:16px;align-items:center;justify-content:space-between;margin-bottom:20px}.categories-toolbar p{font-size:13px;color:var(--ej-muted);line-height:1.8;margin:0}.category-add{border:1px solid var(--ej-ink);border-radius:99px;background:var(--ej-ink);color:var(--ej-surface);padding:11px 18px;white-space:nowrap;cursor:pointer;font:inherit;font-size:13px}.category-table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}th,td{padding:16px 12px;border-bottom:1px solid var(--ej-hairline)}th{background:var(--ej-canvas);color:var(--ej-muted);font-weight:400;white-space:nowrap}.category-description{max-width:350px;overflow-wrap:anywhere}td>span{background:var(--studio-lime-soft);padding:4px 8px;border-radius:99px;font-size:11px}td>span.disabled{background:var(--ej-canvas);color:var(--ej-muted)}@media(max-width:760px){.categories-panel{padding:18px}.categories-toolbar{align-items:flex-start;flex-direction:column}}
</style>
