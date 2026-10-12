<template>
  <div class="edit-profile-page">
    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="logo" @click="$router.push('/')">EasyJob</div>
      <span class="page-title">编辑资料</span>
      <AppNavigation />
    </nav>

    <main class="container">
      <header class="page-header">
        <div>
          <h1>编辑资料</h1>
          <p class="page-description">头像、昵称和简介会出现在你的个人空间、文章署名和评论里。</p>
        </div>
      </header>

      <form class="profile-layout" @submit.prevent="saveProfile">
        <!-- 左侧：名片预览，点击头像即可更换 -->
        <aside class="form-card profile-card">
          <label class="avatar-upload" :class="{ uploading: avatarUploading }">
            <img
              v-if="!avatarUploading"
              :src="avatarUrl(profile.avatar, profile.nickName)"
              alt="头像预览"
              class="avatar-preview"
              @error="onAvatarError($event, profile.nickName)"
            >
            <div v-else class="avatar-progress" role="progressbar" :aria-valuenow="avatarProgress" aria-valuemin="0" aria-valuemax="100" aria-label="头像上传进度">
              <div class="progress-bar" :style="{ height: avatarProgress + '%' }"></div>
              <span class="progress-text">{{ avatarProgress }}%</span>
            </div>
            <span v-if="!avatarUploading" class="avatar-overlay" aria-hidden="true">更换头像</span>
            <input
              type="file"
              accept="image/*"
              class="file-input"
              aria-label="上传新头像"
              :disabled="avatarUploading"
              @change="uploadAvatar"
            >
          </label>
          <div class="profile-card-text">
            <p class="profile-name">{{ profile.nickName.trim() || '你的昵称' }}</p>
            <p class="profile-intro">{{ profile.personIntroduction.trim() || '还没有个人简介' }}</p>
            <p class="profile-hint">点击头像更换，图片不超过 15MB</p>
          </div>
        </aside>

        <div class="profile-sections">
          <section class="form-card profile-section" aria-labelledby="profile-basic-title">
            <div class="section-heading"><span class="section-index">01</span><h2 id="profile-basic-title">基本信息</h2></div>

            <div class="form-item">
              <label for="profile-nickname">昵称 <span class="required">*</span></label>
              <input
                id="profile-nickname"
                v-model="profile.nickName"
                type="text"
                placeholder="2–20 个字符"
                maxlength="20"
              >
            </div>

            <div class="form-row">
              <div class="form-item">
                <label for="profile-sex">性别</label>
                <select id="profile-sex" v-model="profile.sex">
                  <option :value="2">未知</option>
                  <option :value="1">男</option>
                  <option :value="0">女</option>
                </select>
              </div>
              <div class="form-item">
                <label for="profile-birthday">生日</label>
                <input
                  id="profile-birthday"
                  v-model="profile.birthday"
                  type="date"
                >
              </div>
            </div>

            <div class="form-item">
              <label for="profile-school">学校</label>
              <input
                id="profile-school"
                v-model="profile.school"
                type="text"
                placeholder="请输入学校名称"
                maxlength="100"
              >
            </div>
          </section>

          <section class="form-card profile-section" aria-labelledby="profile-display-title">
            <div class="section-heading"><span class="section-index">02</span><h2 id="profile-display-title">个人展示</h2></div>

            <div class="form-item">
              <label for="profile-intro">个人简介 <span class="field-count">{{ profile.personIntroduction.length }}/500</span></label>
              <textarea
                id="profile-intro"
                v-model="profile.personIntroduction"
                placeholder="介绍一下自己吧，比如关注的方向、正在做的项目"
                rows="3"
                maxlength="500"
              ></textarea>
            </div>

            <div class="form-item">
              <label for="profile-notice">空间公告 <span class="field-count">{{ profile.noticeInfo.length }}/500</span></label>
              <textarea
                id="profile-notice"
                v-model="profile.noticeInfo"
                placeholder="显示在个人空间侧栏的公告"
                rows="3"
                maxlength="500"
              ></textarea>
            </div>

            <div class="form-item">
              <label for="profile-theme">主题</label>
              <select id="profile-theme" v-model="profile.theme">
                <option :value="1">默认主题</option>
                <option :value="2">暗黑主题</option>
                <option :value="3">梦幻主题</option>
              </select>
            </div>
          </section>

          <div class="form-actions">
            <button type="button" class="cancel-btn" @click="goBackOr(router, '/user-space')">取消</button>
            <button type="submit" class="submit-btn" :disabled="saving || avatarUploading">
              {{ saving ? '保存中...' : '保存修改' }}
            </button>
          </div>
        </div>
      </form>
    </main>

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
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { goBackOr } from '../utils/navigation'
import LoginForm from '../components/LoginForm.vue'
import RegisterForm from '../components/RegisterForm.vue'
import request from '../utils/request'
import { uploadFile } from '../utils/upload'
import { avatarUrl, onAvatarError } from '../utils/avatar'
import { eventBus, EVENT_AUTH_EXPIRED } from '../utils/eventBus'

const router = useRouter()
const saving = ref(false)
const avatarUploading = ref(false)
const avatarProgress = ref(0)

const profile = ref({
  nickName: '',
  avatar: '',
  sex: 2,
  birthday: '',
  school: '',
  personIntroduction: '',
  noticeInfo: '',
  theme: 1
})

// 获取用户信息
async function fetchProfile() {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    alert('请先登录')
    router.push('/login')
    return
  }
  
  try {
    const res = await request.get(`/user/space/${userId}`)
    console.log('个人资料:', res)
    if (res.code === 200 && res.data) {
      profile.value = {
        nickName: res.data.nickName || '',
        avatar: res.data.avatar || '',
        sex: res.data.sex ?? 2,
        birthday: res.data.birthday || '',
        school: res.data.school || '',
        personIntroduction: res.data.personIntroduction || '',
        noticeInfo: res.data.noticeInfo || '',
        theme: res.data.theme ?? 1
      }
    }
  } catch (error) {
    console.error('获取用户信息失败:', error)
  }
}

// 保存资料
async function saveProfile() {
  if (!profile.value.nickName.trim()) {
    alert('请输入昵称')
    return
  }
  
  if (profile.value.nickName.length < 2 || profile.value.nickName.length > 20) {
    alert('昵称长度应在2-20个字符之间')
    return
  }
  
  saving.value = true
  try {
    const res = await request.put('/user/update', {
      nickName: profile.value.nickName,
      avatar: profile.value.avatar,
      sex: profile.value.sex,
      birthday: profile.value.birthday || null,
      school: profile.value.school,
      personIntroduction: profile.value.personIntroduction,
      noticeInfo: profile.value.noticeInfo,
      theme: profile.value.theme
    })
    
    if (res.code === 200) {
      // 更新本地存储（缓存用户信息，避免重复查询）
      localStorage.setItem('nickName', profile.value.nickName)
      localStorage.setItem('avatar', profile.value.avatar)
      alert('保存成功')
      // 回到进入编辑前的页面，不在历史里再叠一条个人空间
      goBackOr(router, '/user-space')
    } else {
      alert(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存失败:', error)
    alert('保存失败')
  } finally {
    saving.value = false
  }
}

// 上传头像
async function uploadAvatar(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  
  // 验证文件大小
  if (file.size > 15 * 1024 * 1024) {
    alert('文件大小不能超过15MB')
    return
  }
  
  avatarUploading.value = true
  avatarProgress.value = 0
  
  try {
    const res = await uploadFile({
      url: '/file/upload-avatar',
      file,
      onProgress: (percent) => {
        avatarProgress.value = percent
      }
    })
    
    if (res.code === 200 && res.data?.url) {
      profile.value.avatar = res.data.url
      // 同步更新本地缓存，保证聊天页面使用最新头像
      localStorage.setItem('avatar', res.data.url)
      alert('头像上传成功')
    } else {
      alert(res.message || '上传失败')
    }
  } catch (error: any) {
    console.error('上传失败:', error)
    alert(error.message || '上传失败')
  } finally {
    avatarUploading.value = false
    avatarProgress.value = 0
    target.value = ''
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
  fetchProfile()
})

onUnmounted(() => {
  eventBus.off(EVENT_AUTH_EXPIRED, handleAuthExpired)
})
</script>

<style scoped>
/* 纸面卡片、输入框、按钮与标题的配色见 styles/theme.css，这里只负责布局 */
.edit-profile-page {
  min-height: 100vh;
}

.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.container {
  max-width: 1040px;
  margin: 104px auto 56px;
  padding: 0 24px;
}

.page-header {
  margin-bottom: 24px;
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

.profile-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 24px;
  align-items: start;
}

/* 左侧名片 */
.profile-card {
  position: sticky;
  top: 96px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 24px 24px;
  text-align: center;
}

.avatar-upload {
  position: relative;
  display: block;
  width: 132px;
  height: 132px;
  flex-shrink: 0;
  border-radius: 50%;
  cursor: pointer;
}

.avatar-upload:focus-within {
  outline: 2px solid var(--ej-accent);
  outline-offset: 4px;
}

.avatar-preview {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 1.5px solid var(--ej-ink);
  box-shadow: var(--ej-shadow);
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #11110fa6;
  color: var(--ej-surface);
  font-size: 13px;
  font-weight: 700;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
}

.avatar-upload:hover .avatar-overlay,
.avatar-upload:focus-within .avatar-overlay {
  opacity: 1;
}

.file-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.file-input:disabled {
  cursor: progress;
}

/* 上传进度从底部往上填充 */
.avatar-progress {
  position: relative;
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  overflow: hidden;
  border-radius: 50%;
  border: 1.5px solid var(--ej-ink);
  background: var(--ej-canvas);
}

.avatar-progress .progress-bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--studio-lime);
  transition: height 0.3s ease;
}

.avatar-progress .progress-text {
  position: relative;
  color: var(--ej-ink);
  font-size: 18px;
  font-weight: 800;
}

.profile-card-text {
  width: 100%;
  min-width: 0;
}

.profile-name {
  margin-top: 18px;
  color: var(--ej-ink);
  font-size: 20px;
  font-weight: 850;
  letter-spacing: -0.03em;
  overflow-wrap: anywhere;
}

.profile-intro {
  margin-top: 6px;
  color: #47453f;
  font-size: 13px;
  line-height: 1.7;
  overflow: hidden;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.profile-hint {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--ej-hairline);
  color: var(--ej-muted);
  font-size: 11px;
}

/* 右侧分组表单 */
.profile-sections {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}

.profile-section {
  padding: 26px 28px 6px;
}

.section-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 20px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--ej-hairline);
}

.section-index {
  color: var(--ej-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
}

.section-heading h2 {
  color: var(--ej-ink);
  font-size: 16px;
  font-weight: 800;
}

.form-item {
  margin-bottom: 20px;
}

.form-item > label {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 8px;
  color: var(--ej-ink);
  font-size: 13px;
  font-weight: 600;
}

.required {
  color: var(--studio-coral);
}

/* 字数统计靠右 */
.field-count {
  margin-left: auto;
  color: var(--ej-muted);
  font-size: 11px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.form-item input,
.form-item textarea,
.form-item select {
  width: 100%;
  padding: 12px 16px;
  font-size: 14px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-item textarea {
  min-height: 96px;
  line-height: 1.7;
  resize: vertical;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.cancel-btn,
.submit-btn {
  min-width: 132px;
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

/* 窄屏：名片横排在表单上方 */
@media (max-width: 860px) {
  .profile-layout {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .profile-card {
    position: static;
    flex-direction: row;
    gap: 18px;
    padding: 20px;
    text-align: left;
  }

  .avatar-upload {
    width: 88px;
    height: 88px;
  }

  .profile-name {
    margin-top: 0;
    font-size: 18px;
  }

  .profile-hint {
    margin-top: 8px;
    padding-top: 0;
    border-top: 0;
  }
}

@media (max-width: 600px) {
  .container {
    margin-top: 82px;
    padding: 0 16px;
  }

  .page-header h1 {
    font-size: 24px;
  }

  .profile-section {
    padding: 22px 18px 4px;
  }

  .form-row {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .form-actions > button {
    flex: 1;
    min-width: 0;
  }
}
</style>
