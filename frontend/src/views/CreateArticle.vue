<template>
  <div class="article-editor-page">
    <StarBackground />
    
    <!-- 顶部导航栏 -->
    <nav class="top-bar">
      <div class="top-bar-left">
        <div class="logo" @click="$router.push('/')">
          <svg class="logo-icon" viewBox="0 0 1024 1024" fill="currentColor">
            <path d="M512 1024c282.771692 0 512-229.228308 512-512S794.771692 0 512 0 0 229.228308 0 512s229.228308 512 512 512z m0-59.076923C261.858462 964.923077 59.076923 762.141538 59.076923 512S261.858462 59.076923 512 59.076923s452.923077 202.781538 452.923077 452.923077-202.781538 452.923077-452.923077 452.923077z"/>
            <path d="M464.945231 748.642462c15.399385 3.042462 31.133538 4.588308 47.054769 4.588307 133.228308 0 241.230769-108.002462 241.230769-241.230769S645.228308 270.769231 512 270.769231 270.769231 378.771692 270.769231 512c0 15.921231 1.545846 31.655385 4.588307 47.054769a24.615385 24.615385 0 0 0 48.295385-9.550769A193.053538 193.053538 0 0 1 320 512c0-106.043077 85.956923-192 192-192S704 405.956923 704 512 618.043077 704 512 704c-12.701538 0-25.245538-1.230769-37.494154-3.652923a24.615385 24.615385 0 1 0-9.550769 48.295385z"/>
            <path d="M512 512m-78.769231 0a78.769231 78.769231 0 1 0 157.538462 0 78.769231 78.769231 0 1 0-157.538462 0Z"/>
            <path d="M510.385231 498.294154C396.465231 543.123692 320 653.351385 320 777.846154a24.615385 24.615385 0 1 0 49.230769 0 251.145846 251.145846 0 0 1 159.182769-233.737846 24.615385 24.615385 0 0 0-18.018461-45.814154z"/>
          </svg>
          <span class="logo-text">EasyJob</span>
        </div>
        <span class="page-title">{{ isEditMode ? '编辑文章' : '写文章' }}</span>
      </div>
      <div class="top-bar-buttons">
        <button class="btn btn-cancel" @click="goBack">取消</button>
        <button class="btn btn-draft" @click="saveDraft">保存草稿</button>
        <button class="btn btn-publish" @click="publishArticle">发布文章</button>
      </div>
    </nav>

    <div class="editor-container">
      <!-- 左侧主编辑区 -->
      <div class="editor-main">
        <!-- 标题输入 -->
        <input 
          v-model="article.title"
          type="text"
          class="title-input"
          placeholder="请输入文章标题..."
          maxlength="100"
        >
        
        <!-- 摘要输入 -->
        <textarea
          v-model="article.summary"
          class="summary-input"
          placeholder="请输入文章摘要（选填，用于文章列表展示）..."
          rows="2"
          maxlength="300"
        ></textarea>
        
        <!-- 富文本编辑器 -->
        <div class="editor-wrapper">
          <Toolbar
            class="toolbar"
            :editor="editorRef"
            :defaultConfig="toolbarConfig"
            mode="default"
          />
          <Editor
            class="editor"
            v-model="valueHtml"
            :defaultConfig="editorConfig"
            mode="default"
            @onCreated="handleCreated"
          />
        </div>
        
        <div class="editor-hint">
          <svg class="hint-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7zm2.85 11.1l-.85.6V16h-4v-2.3l-.85-.6C7.8 12.16 7 10.63 7 9c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.63-.8 3.16-2.15 4.1z"/>
          </svg>
          <strong>提示：</strong>支持 Markdown 快捷输入，如 # 标题、``` 代码块、> 引用
        </div>
      </div>
      
      <!-- 右侧设置面板 -->
      <div class="editor-sidebar">
        <div class="sidebar-card">
          <h3>文章设置</h3>
          
          <!-- 封面上传 -->
          <div class="setting-item">
            <label>文章封面</label>
            <div class="cover-upload" @click="triggerCoverUpload">
              <img 
                v-if="article.coverImage" 
                :src="getImageUrl(article.coverImage)" 
                alt="封面预览"
                class="cover-preview"
              >
              <div v-else-if="coverUploading" class="upload-progress-container">
                <div class="upload-progress-bar" :style="{ width: coverProgress + '%' }"></div>
                <span class="upload-progress-text">{{ coverProgress }}%</span>
              </div>
              <div v-else class="upload-placeholder">
                <svg viewBox="0 0 24 24" width="32" height="32">
                  <path fill="#999" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
                </svg>
                <span>上传封面</span>
              </div>
              <input 
                ref="coverInput"
                type="file" 
                accept="image/*" 
                @change="uploadCover"
                class="file-input"
              >
            </div>
            <button v-if="article.coverImage" class="remove-cover" @click.stop="removeCover">
              移除封面
            </button>
          </div>
          
          <!-- 文章分类 -->
          <div class="setting-item">
            <label>文章分类 <span class="required">*</span></label>
            <select v-model="article.categoryId" class="category-select" :class="{ 'placeholder': !article.categoryId }">
              <option value="">请选择分类</option>
              <option v-for="category in categories" :key="category.categoryId" :value="category.categoryId">
                {{ category.categoryName }}
              </option>
            </select>
          </div>
          
          <!-- 文章类型 -->
          <div class="setting-item">
            <label>文章类型</label>
            <div class="radio-group">
              <label class="radio-item">
                <input type="radio" v-model="article.isOriginal" :value="true">
                <span class="radio-label">原创</span>
              </label>
              <label class="radio-item">
                <input type="radio" v-model="article.isOriginal" :value="false">
                <span class="radio-label">转载</span>
              </label>
            </div>
          </div>
          
          <!-- 文章标签 -->
          <div class="setting-item">
            <label>文章标签</label>
            <div class="tag-input-wrapper">
              <input 
                v-model="tagInput"
                type="text" 
                class="tag-input"
                placeholder="输入标签按回车添加"
                @input="searchTags"
                @keyup.enter="addTag"
                @blur="hideTagSuggestions"
                maxlength="20"
              >
              <button class="tag-add-btn" @click="addTag" type="button">+</button>
              
              <!-- 标签联想列表 -->
              <div v-if="showTagSuggestions && tagSuggestions.length > 0" class="tag-suggestions">
                <div 
                  v-for="tag in tagSuggestions" 
                  :key="tag.tagId"
                  class="tag-suggestion-item"
                  @mousedown.prevent="selectSuggestionTag(tag.tagName)"
                >
                  <span class="tag-name">{{ tag.tagName }}</span>
                  <span class="tag-count">{{ tag.useCount }}次使用</span>
                </div>
              </div>
            </div>
            
            <!-- 热门标签 -->
            <div v-if="hotTags.length > 0 && tagList.length < 5" class="hot-tags">
              <span class="hot-tags-label">热门:</span>
              <span 
                v-for="tag in hotTags.slice(0, 8)" 
                :key="tag.tagId"
                class="hot-tag-item"
                @click="addHotTag(tag.tagName)"
              >
                {{ tag.tagName }}
              </span>
            </div>
            
            <div class="tag-list" v-if="tagList.length > 0">
              <span class="tag-item" v-for="(tag, index) in tagList" :key="index">
                {{ tag }}
                <span class="tag-remove" @click="removeTag(index)">×</span>
              </span>
            </div>
            <div class="tag-hint">最多添加5个标签，用于文章分类和搜索</div>
          </div>
        </div>
        
        <!-- 快捷键提示 -->
        <div class="sidebar-card shortcuts">
          <h3>快捷键</h3>
          <div class="shortcut-item">
            <span class="key">Ctrl + S</span>
            <span>保存草稿</span>
          </div>
          <div class="shortcut-item">
            <span class="key">Ctrl + B</span>
            <span>加粗</span>
          </div>
          <div class="shortcut-item">
            <span class="key">Ctrl + I</span>
            <span>斜体</span>
          </div>
          <div class="shortcut-item">
            <span class="key">```</span>
            <span>代码块</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 登录弹窗 -->
  <el-dialog v-model="showLoginDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
    <LoginForm @success="handleLoginSuccess" @switchToRegister="switchToRegister" />
  </el-dialog>
  <el-dialog v-model="showRegisterDialog" title="" :width="dialogWidth" :close-on-click-modal="true" class="modern-dialog">
    <RegisterForm @success="handleRegisterSuccess" @switchToLogin="switchToLogin" />
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, shallowRef, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StarBackground from '../components/StarBackground.vue'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { uploadFile } from '../utils/upload'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'

const route = useRoute()
const router = useRouter()
const coverInput = ref<HTMLInputElement | null>(null)
const coverUploading = ref(false)
const coverProgress = ref(0)

const article = ref({
  articleId: '',
  title: '',
  summary: '',
  content: '',
  coverImage: '',
  tags: '',
  categoryId: '',  // 新增：分类ID
  isOriginal: true,
  status: 0
})

// 标签输入
const tagInput = ref('')
const tagList = ref<string[]>([])
const tagSuggestions = ref<any[]>([])  // 标签联想列表
const showTagSuggestions = ref(false)  // 是否显示联想
const hotTags = ref<any[]>([])  // 热门标签
let searchTimeout: any = null  // 防抖定时器

// 分类列表
const categories = ref<any[]>([])

// 编辑器实例
const editorRef = shallowRef()
const valueHtml = ref('')

const isEditMode = computed(() => !!route.query.id)

// 工具栏配置
const toolbarConfig = {
  toolbarKeys: [
    'headerSelect',
    'blockquote',
    '|',
    'bold',
    'underline',
    'italic',
    'through',
    'color',
    'bgColor',
    '|',
    'fontSize',
    'lineHeight',
    '|',
    'bulletedList',
    'numberedList',
    'todo',
    '|',
    'insertLink',
    'uploadImage',
    'insertTable',
    'codeBlock',
    'divider',
    '|',
    'undo',
    'redo',
    '|',
    'fullScreen'
  ]
}

// 编辑器配置
const editorConfig = {
  placeholder: '开始创作你的文章...\n\n支持 Markdown 快捷输入：\n# 一级标题\n## 二级标题\n``` 代码块\n> 引用\n- 列表',
  MENU_CONF: {
    uploadImage: {
      async customUpload(file: File, insertFn: Function) {
        const formData = new FormData()
        formData.append('file', file)
        
        try {
          const res = await request.post('/file/upload-article-image', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          })
          
          if (res.code === 200 && res.data?.url) {
            // 直接使用相对路径，让 Vite 代理（本地）或 Nginx（服务器）处理
            insertFn(res.data.url, '', res.data.url)
          } else {
            alert(res.message || '图片上传失败')
          }
        } catch (error) {
          console.error('上传失败:', error)
          alert('图片上传失败')
        }
      },
      maxFileSize: 15 * 1024 * 1024,
      allowedFileTypes: ['image/*']
    },
    codeSelectLang: {
      codeLangs: [
        { text: 'Java', value: 'java' },
        { text: 'JavaScript', value: 'javascript' },
        { text: 'TypeScript', value: 'typescript' },
        { text: 'Python', value: 'python' },
        { text: 'Go', value: 'go' },
        { text: 'C/C++', value: 'cpp' },
        { text: 'SQL', value: 'sql' },
        { text: 'HTML', value: 'html' },
        { text: 'CSS', value: 'css' },
        { text: 'Shell', value: 'bash' },
        { text: 'JSON', value: 'json' },
        { text: 'XML', value: 'xml' }
      ]
    }
  }
}

// 编辑器创建完成
function handleCreated(editor: any) {
  editorRef.value = editor
}

// 获取分类列表
async function fetchCategories() {
  try {
    const res = await request.get('/category/list')
    if (res.code === 200) {
      categories.value = res.data || []
    }
  } catch (error) {
    console.error('获取分类失败:', error)
  }
}

// 获取热门标签
async function fetchHotTags() {
  try {
    const res = await request.get('/tag/hot', { params: { limit: 10 } })
    if (res.code === 200) {
      hotTags.value = res.data || []
    }
  } catch (error) {
    console.error('获取热门标签失败:', error)
  }
}

// 搜索标签（防抖）
function searchTags() {
  clearTimeout(searchTimeout)
  const keyword = tagInput.value.trim()
  
  if (!keyword) {
    showTagSuggestions.value = false
    return
  }
  
  searchTimeout = setTimeout(async () => {
    try {
      const res = await request.get('/tag/search', {
        params: { keyword, limit: 5 }
      })
      if (res.code === 200) {
        tagSuggestions.value = res.data || []
        showTagSuggestions.value = tagSuggestions.value.length > 0
      }
    } catch (error) {
      console.error('搜索标签失败:', error)
    }
  }, 300)
}

// 选择联想标签
function selectSuggestionTag(tagName: string) {
  tagInput.value = tagName
  showTagSuggestions.value = false
  addTag()
}

// 隐藏联想列表
function hideTagSuggestions() {
  setTimeout(() => {
    showTagSuggestions.value = false
  }, 200)
}

// 添加热门标签
function addHotTag(tagName: string) {
  if (tagList.value.length >= 5) {
    alert('最多添加5个标签')
    return
  }
  if (tagList.value.includes(tagName)) {
    return
  }
  tagList.value.push(tagName)
}

// 获取文章详情（编辑模式）
async function fetchArticle() {
  const articleId = route.query.id as string
  if (!articleId) return
  
  try {
    const res = await request.get(`/article/detail/${articleId}`)
    if (res.code === 200 && res.data) {
      article.value = {
        ...article.value,
        ...res.data,
        articleId: articleId,
        // categoryId: null转为空字符串，确保select能正确显示placeholder
        categoryId: res.data.categoryId || '',
        // isOriginal: 后端返回0/1，转为布尔值，null/undefined默认为true
        isOriginal: res.data.isOriginal == null ? true : Boolean(res.data.isOriginal)
      }
      valueHtml.value = res.data.content || ''
      // 解析标签（新版：tags 是对象数组）
      if (res.data.tags && Array.isArray(res.data.tags)) {
        tagList.value = res.data.tags.map((tag: any) => tag.tagName)
      } else if (typeof res.data.tags === 'string' && res.data.tags) {
        // 兼容旧版：tags 是逗号分隔字符串
        tagList.value = res.data.tags.split(',').filter((t: string) => t.trim())
      }
    }
  } catch (error) {
    console.error('获取文章失败:', error)
  }
}

// 保存草稿
async function saveDraft() {
  if (!article.value.title.trim()) {
    alert('请输入文章标题')
    return
  }
  
  if (!article.value.categoryId) {
    alert('请选择文章分类')
    return
  }
  
  try {
    const data = {
      ...article.value,
      content: valueHtml.value,
      status: 0,
      isOriginal: article.value.isOriginal ? 1 : 0,
      tagNames: tagList.value,
      tags: undefined  // 清除旧版tags字段，避免类型冲突
    }
    
    let res
    if (isEditMode.value) {
      res = await request.put(`/article/${article.value.articleId}`, data)
    } else {
      res = await request.post('/article/create', data)
    }
    
    if (res.code === 200) {
      alert('保存成功')
      if (!isEditMode.value && res.data?.articleId) {
        router.replace(`/edit-article?id=${res.data.articleId}`)
      }
    } else {
      alert(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存失败:', error)
    alert('保存失败')
  }
}

// 发布文章
async function publishArticle() {
  if (!article.value.title.trim()) {
    alert('请输入文章标题')
    return
  }
  
  if (!valueHtml.value.trim() || valueHtml.value === '<p><br></p>') {
    alert('请输入文章内容')
    return
  }
  
  if (!article.value.categoryId) {
    alert('请选择文章分类')
    return
  }
  
  try {
    const data = {
      ...article.value,
      content: valueHtml.value,
      status: 1,
      isOriginal: article.value.isOriginal ? 1 : 0,
      tagNames: tagList.value,
      tags: undefined  // 清除旧版tags字段，避免类型冲突
    }
    
    let res
    if (isEditMode.value) {
      res = await request.put(`/article/${article.value.articleId}`, data)
    } else {
      res = await request.post('/article/create', data)
    }
    
    if (res.code === 200) {
      alert('发布成功')
      router.push('/user-space')
    } else {
      alert(res.message || '发布失败')
    }
  } catch (error) {
    console.error('发布失败:', error)
    alert('发布失败')
  }
}

// 触发封面上传
function triggerCoverUpload() {
  coverInput.value?.click()
}

// 上传封面
async function uploadCover(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  
  coverUploading.value = true
  coverProgress.value = 0
  
  try {
    const res = await uploadFile({
      url: '/file/upload-cover',
      file,
      onProgress: (percent) => {
        coverProgress.value = percent
      }
    })
    
    if (res.code === 200 && res.data?.url) {
      article.value.coverImage = res.data.url
    } else {
      alert(res.message || '上传失败')
    }
  } catch (error: any) {
    console.error('上传失败:', error)
    alert(error.message || '上传失败')
  } finally {
    coverUploading.value = false
    coverProgress.value = 0
    target.value = ''
  }
}

// 移除封面
function removeCover() {
  article.value.coverImage = ''
}

// 添加标签
function addTag() {
  const tag = tagInput.value.trim()
  if (!tag) return
  
  if (tagList.value.length >= 5) {
    alert('最多添加5个标签')
    return
  }
  
  if (tagList.value.includes(tag)) {
    alert('标签已存在')
    return
  }
  
  tagList.value.push(tag)
  tagInput.value = ''
  showTagSuggestions.value = false
}

// 删除标签
function removeTag(index: number) {
  tagList.value.splice(index, 1)
}

// 返回
function goBack() {
  if (valueHtml.value && valueHtml.value !== '<p><br></p>') {
    if (!confirm('确定要离开吗？未保存的内容将丢失')) {
      return
    }
  }
  router.back()
}

function getImageUrl(url: string | undefined): string {
  if (!url) return ''
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/uploads')) return url
  return url
}

// 快捷键
function handleKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    saveDraft()
  }
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
  fetchCategories()  // 获取分类列表
  fetchHotTags()     // 获取热门标签
  if (isEditMode.value) {
    fetchArticle()
  }
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
  // 销毁编辑器
  if (editorRef.value) {
    editorRef.value.destroy()
  }
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.article-editor-page {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.article-editor-page::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: #f5f7fa;
  z-index: -2;
}

/* 顶部导航栏 */
.top-bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 60px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  padding: 0 30px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
  z-index: 1000;
}

.top-bar-left {
  display: flex;
  align-items: center;
  gap: 12px;
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

.top-bar-left {
  display: flex;
  align-items: center;
}

.top-bar-buttons {
  display: flex;
  gap: 12px;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
  font-weight: 500;
}

.btn-cancel {
  background: rgba(0, 0, 0, 0.05);
  color: #666;
  border: 1px solid rgba(0, 0, 0, 0.1);
}

.btn-cancel:hover {
  background: rgba(0, 0, 0, 0.1);
}

.btn-draft {
  background: rgba(0, 0, 0, 0.05);
  color: #666;
  border: 1px solid rgba(0, 0, 0, 0.2);
}

.btn-draft:hover {
  background: rgba(0, 0, 0, 0.1);
  border-color: rgba(0, 0, 0, 0.3);
}

.btn-publish {
  background: white;
  color: #333;
}

.btn-publish:hover {
  background: #f0f0f0;
}

/* 编辑器容器 */
.editor-container {
  margin-top: 60px;
  flex: 1;
  padding: 20px;
  display: flex;
  gap: 20px;
  max-width: 1400px;
  margin-left: auto;
  margin-right: auto;
  width: 100%;
}

.editor-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.title-input {
  width: 100%;
  padding: 20px 24px;
  background: white;
  border: none;
  border-radius: 12px 12px 0 0;
  font-size: 28px;
  font-weight: 600;
  color: #333;
  outline: none;
}

.title-input::placeholder {
  color: #ccc;
}

.summary-input {
  width: 100%;
  padding: 15px 24px;
  background: white;
  border: none;
  border-top: 1px solid #f0f0f0;
  font-size: 15px;
  color: #666;
  outline: none;
  resize: none;
}

.summary-input::placeholder {
  color: #bbb;
}

.editor-wrapper {
  flex: 1;
  background: white;
  border-radius: 0 0 12px 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 500px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
}

.toolbar {
  border-bottom: 1px solid #e8e8e8 !important;
}

.editor {
  flex: 1;
  overflow-y: auto;
}

:deep(.w-e-text-container) {
  min-height: 400px !important;
}

:deep(.w-e-text-placeholder) {
  font-style: normal;
  color: #bbb;
  line-height: 1.8;
}

/* 代码块样式 */
:deep(pre) {
  background: #1e1e1e !important;
  border-radius: 8px;
  padding: 16px;
  margin: 12px 0;
  overflow-x: auto;
}

:deep(pre code) {
  font-family: 'Fira Code', 'Consolas', 'Monaco', monospace;
  font-size: 14px;
  line-height: 1.6;
  color: #d4d4d4;
}

:deep(code) {
  font-family: 'Fira Code', 'Consolas', 'Monaco', monospace;
  background: #f6f8fa;
  padding: 2px 6px;
  border-radius: 4px;
  color: #d73a49;
  font-size: 14px;
}

.editor-hint {
  margin-top: 12px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 8px;
  font-size: 13px;
  color: #666;
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint-icon {
  width: 18px;
  height: 18px;
  color: #faad14;
  flex-shrink: 0;
}

.editor-hint strong {
  color: #333;
}

/* 右侧边栏 */
.editor-sidebar {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sidebar-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
}

.sidebar-card h3 {
  font-size: 16px;
  font-weight: 600;
  color: #333;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f0f0;
}

.setting-item {
  margin-bottom: 20px;
}

.setting-item:last-child {
  margin-bottom: 0;
}

.setting-item > label {
  display: block;
  font-size: 14px;
  color: #666;
  margin-bottom: 10px;
  font-weight: 500;
}

.cover-upload {
  position: relative;
  width: 100%;
  height: 140px;
  border: 2px dashed #e0e0e0;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.3s;
}

.cover-upload:hover {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.02);
}

.cover-preview {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.upload-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #999;
  font-size: 14px;
}

.upload-progress-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  background: #f5f7fa;
}

.upload-progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 4px;
  background: #409eff;
  transition: width 0.2s ease;
}

.upload-progress-text {
  font-size: 14px;
  font-weight: 600;
  color: #409eff;
}

.file-input {
  display: none;
}

.remove-cover {
  margin-top: 10px;
  padding: 6px 12px;
  background: none;
  border: 1px solid #ff4d4f;
  color: #ff4d4f;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.3s;
}

.remove-cover:hover {
  background: #ff4d4f;
  color: white;
}

.radio-group {
  display: flex;
  gap: 20px;
}

.radio-item {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.radio-item input {
  cursor: pointer;
  accent-color: #667eea;
}

.radio-label {
  font-size: 14px;
  color: #333;
}

/* 分类选择 */
.category-select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  cursor: pointer;
  transition: border-color 0.3s;
  background: white;
}

.category-select.placeholder {
  color: #999;
}

.category-select:focus {
  border-color: #667eea;
}

.required {
  color: #ff4757;
  margin-left: 4px;
}

/* 标签输入 */
.tag-input-wrapper {
  position: relative;
  display: flex;
  gap: 8px;
}

.tag-input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s;
}

.tag-input:focus {
  border-color: #667eea;
}

.tag-add-btn {
  width: 40px;
  height: 40px;
  border: 1px solid #667eea;
  background: white;
  color: #667eea;
  border-radius: 8px;
  font-size: 20px;
  cursor: pointer;
  transition: all 0.3s;
}

.tag-add-btn:hover {
  background: #667eea;
  color: white;
}

/* 标签联想列表 */
.tag-suggestions {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 48px;
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
}

.tag-suggestion-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.tag-suggestion-item:hover {
  background: #f8f9fa;
}

.tag-name {
  font-size: 14px;
  color: #333;
}

.tag-count {
  font-size: 12px;
  color: #999;
}

/* 热门标签 */
.hot-tags {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.hot-tags-label {
  font-size: 12px;
  color: #999;
}

.hot-tag-item {
  display: inline-block;
  padding: 4px 12px;
  background: #f8f9fa;
  color: #667eea;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.hot-tag-item:hover {
  background: rgba(102, 126, 234, 0.1);
  transform: translateY(-2px);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.tag-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
  border-radius: 16px;
  font-size: 13px;
}

.tag-remove {
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.tag-remove:hover {
  opacity: 1;
}

.tag-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #999;
}

/* 快捷键提示 */
.shortcuts {
  font-size: 13px;
}

.shortcut-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  color: #666;
}

.shortcut-item:not(:last-child) {
  border-bottom: 1px solid #f5f5f5;
}

.key {
  background: #f0f0f0;
  padding: 3px 8px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  color: #333;
}

/* 响应式 */
@media (max-width: 1000px) {
  .editor-sidebar {
    display: none;
  }
}

@media (max-width: 768px) {
  .top-bar {
    padding: 0 12px;
    height: 55px;
  }
  
  .top-bar-left {
    gap: 8px;
  }
  
  .logo {
    font-size: 18px;
  }
  
  .divider {
    display: none;
  }
  
  .page-title {
    font-size: 14px;
  }
  
  .top-bar-buttons {
    gap: 6px;
  }
  
  .btn {
    padding: 6px 12px;
    font-size: 12px;
    border-radius: 6px;
  }
  
  .editor-container {
    padding: 10px;
    margin-top: 65px;
  }
  
  .editor-main {
    padding: 15px;
    border-radius: 12px;
  }
  
  .title-input {
    font-size: 18px;
    padding: 12px 15px;
  }
  
  .summary-input {
    font-size: 14px;
    padding: 10px 15px;
  }
  
  .toolbar-wrapper {
    padding: 8px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
}

@media (max-width: 480px) {
  .top-bar {
    padding: 0 10px;
    height: 50px;
  }
  
  .top-bar-left {
    gap: 6px;
  }
  
  .logo {
    font-size: 16px;
  }
  
  .logo-icon {
    width: 24px;
    height: 24px;
  }
  
  .logo-text {
    display: none;
  }
  
  .page-title {
    font-size: 12px;
  }
  
  .top-bar-buttons {
    gap: 4px;
  }
  
  .btn {
    padding: 5px 8px;
    font-size: 11px;
  }
  
  .editor-container {
    padding: 8px;
    margin-top: 58px;
  }
  
  .editor-main {
    padding: 12px;
    border-radius: 10px;
  }
  
  .title-input {
    font-size: 16px;
    padding: 10px 12px;
    border-radius: 8px;
  }
  
  .summary-input {
    font-size: 13px;
    padding: 8px 12px;
  }
  
  /* 工具栏滚动 */
  .toolbar-wrapper {
    padding: 6px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  
  /* 发布弹窗 */
  .publish-modal {
    width: 95%;
    max-height: 85vh;
    border-radius: 15px;
  }
  
  .modal-header h3 {
    font-size: 16px;
  }
  
  .modal-body {
    padding: 15px;
  }
  
  .form-group label {
    font-size: 13px;
  }
  
  .form-input {
    font-size: 14px;
  }
  
  .publish-btn {
    padding: 10px 20px;
    font-size: 13px;
  }
}
</style>
