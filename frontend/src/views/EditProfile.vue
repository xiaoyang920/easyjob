<template>
  <div class="edit-profile-page">
    <StarBackground />
    
    <!-- 导航栏 -->
    <nav class="navbar">
      <div class="logo" @click="$router.push('/')">EasyJob</div>
      <div class="nav-right">
        <button class="nav-btn" @click="$router.push('/user-space')">返回空间</button>
      </div>
    </nav>

    <div class="container">
      <div class="form-card">
        <h1>编辑资料</h1>
        
        <form @submit.prevent="saveProfile">
          <!-- 头像 -->
          <div class="form-item avatar-section">
            <label>头像</label>
            <div class="avatar-upload">
              <img 
                v-if="!avatarUploading"
                :src="getAvatarUrl(profile.avatar)" 
                alt="头像" 
                class="avatar-preview"
                @error="handleAvatarError"
              >
              <div v-if="avatarUploading" class="avatar-progress">
                <div class="progress-bar" :style="{ width: avatarProgress + '%' }"></div>
                <span class="progress-text">{{ avatarProgress }}%</span>
              </div>
              <div v-if="!avatarUploading" class="avatar-overlay">
                <span>更换头像</span>
              </div>
              <input 
                type="file" 
                accept="image/*" 
                @change="uploadAvatar"
                class="file-input"
              >
            </div>
          </div>
          
          <!-- 昵称 -->
          <div class="form-item">
            <label>昵称 <span class="required">*</span></label>
            <input 
              v-model="profile.nickName"
              type="text" 
              placeholder="请输入昵称"
              maxlength="20"
            >
          </div>
          
          <!-- 性别和生日 -->
          <div class="form-row">
            <div class="form-item">
              <label>性别</label>
              <select v-model="profile.sex">
                <option :value="2">未知</option>
                <option :value="1">男</option>
                <option :value="0">女</option>
              </select>
            </div>
            <div class="form-item">
              <label>生日</label>
              <input 
                v-model="profile.birthday"
                type="date"
              >
            </div>
          </div>
          
          <!-- 学校 -->
          <div class="form-item">
            <label>学校</label>
            <input 
              v-model="profile.school"
              type="text" 
              placeholder="请输入学校名称"
              maxlength="100"
            >
          </div>
          
          <!-- 个人简介 -->
          <div class="form-item">
            <label>个人简介</label>
            <textarea 
              v-model="profile.personIntroduction"
              placeholder="介绍一下自己吧~"
              rows="3"
              maxlength="500"
            ></textarea>
          </div>
          
          <!-- 空间公告 -->
          <div class="form-item">
            <label>空间公告</label>
            <textarea 
              v-model="profile.noticeInfo"
              placeholder="设置你的空间公告"
              rows="3"
              maxlength="500"
            ></textarea>
          </div>
          
          <!-- 主题 -->
          <div class="form-item">
            <label>主题</label>
            <select v-model="profile.theme">
              <option :value="1">默认主题</option>
              <option :value="2">暗黑主题</option>
              <option :value="3">梦幻主题</option>
            </select>
          </div>
          
          <!-- 提交按钮 -->
          <div class="form-actions">
            <button type="button" class="cancel-btn" @click="$router.push('/user-space')">取消</button>
            <button type="submit" class="submit-btn" :disabled="saving">
              {{ saving ? '保存中...' : '保存修改' }}
            </button>
          </div>
        </form>
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
import { uploadFile } from '../utils/upload'
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
      router.push('/user-space')
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

// 获取头像URL
function getAvatarUrl(url: string | undefined): string {
  if (!url) return 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/uploads')) return url
  return url
}

function handleAvatarError(e: Event) {
  const target = e.target as HTMLImageElement
  if (target.dataset.errorHandled) return
  target.dataset.errorHandled = 'true'
  target.src = 'https://cube.elemecdn.com/3/7c/3ea6beec64369c2642b92c6726f1epng.png'
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
.edit-profile-page {
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  min-height: 100vh;
  position: relative;
}

.edit-profile-page::before {
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
  justify-content: space-between;
  align-items: center;
  padding: 0 50px;
  z-index: 1000;
}

.logo {
  font-size: 28px;
  font-weight: bold;
  color: #409eff;
  cursor: pointer;
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
  background: #eee;
}

.container {
  max-width: 600px;
  margin: 100px auto 50px;
  padding: 0 20px;
}

.form-card {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20px;
  padding: 40px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
}

.form-card h1 {
  font-size: 24px;
  font-weight: 600;
  color: #333;
  margin-bottom: 35px;
  text-align: center;
}

.form-item {
  margin-bottom: 25px;
}

.form-item > label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #333;
  margin-bottom: 10px;
}

.form-item > label .required {
  color: #ff6b9d;
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 600px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}

.form-item input,
.form-item textarea,
.form-item select {
  width: 100%;
  padding: 14px 18px;
  border: 1.5px solid #e0e0e0;
  border-radius: 12px;
  font-size: 15px;
  color: #333;
  transition: all 0.3s;
  background: white;
}

.form-item input:focus,
.form-item textarea:focus,
.form-item select:focus {
  outline: none;
  border-color: #409eff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1);
}

.form-item input:disabled {
  background: #f5f5f5;
  color: #999;
  cursor: not-allowed;
}

.form-item select {
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23666' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 15px center;
}

.form-item textarea {
  resize: vertical;
  min-height: 100px;
}

.hint {
  display: block;
  font-size: 12px;
  color: #999;
  margin-top: 6px;
}

/* 头像上传 */
.avatar-section {
  text-align: center;
}

.avatar-upload {
  position: relative;
  width: 120px;
  height: 120px;
  margin: 0 auto;
  cursor: pointer;
}

.avatar-preview {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 3px solid #f0f0f0;
  transition: all 0.3s;
}

.avatar-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.3s;
}

.avatar-overlay span {
  color: white;
  font-size: 13px;
}

.avatar-upload:hover .avatar-overlay {
  opacity: 1;
}

.avatar-upload:hover .avatar-preview {
  border-color: #409eff;
}

.file-input {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

/* 头像上传进度条 */
.avatar-progress {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  border: 3px solid #f0f0f0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}

.avatar-progress .progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 100%;
  background: rgba(64, 158, 255, 0.2);
  transition: width 0.3s ease;
}

.avatar-progress .progress-text {
  position: relative;
  z-index: 1;
  font-size: 16px;
  font-weight: 600;
  color: #409eff;
}

/* 按钮 */
.form-actions {
  display: flex;
  gap: 15px;
  margin-top: 35px;
}

.cancel-btn {
  flex: 1;
  padding: 14px;
  background: white;
  border: 1.5px solid #e0e0e0;
  border-radius: 12px;
  color: #666;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.3s;
}

.cancel-btn:hover {
  border-color: #999;
  color: #333;
}

.submit-btn {
  flex: 1;
  padding: 14px;
  background: #409eff;
  border: none;
  border-radius: 12px;
  color: white;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s;
}

.submit-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(64, 158, 255, 0.3);
}

.submit-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .navbar {
    padding: 0 15px;
    height: 55px;
  }
  
  .logo {
    font-size: 20px;
  }
  
  .nav-btn {
    padding: 6px 12px;
    font-size: 12px;
  }
  
  .edit-container {
    margin-top: 75px;
    padding: 20px 15px;
  }
  
  .edit-card {
    padding: 25px 20px;
    border-radius: 15px;
  }
  
  .card-header h2 {
    font-size: 20px;
  }
  
  .avatar-upload {
    width: 100px;
    height: 100px;
  }
  
  .form-item label {
    font-size: 13px;
  }
  
  .form-item input,
  .form-item textarea,
  .form-item select {
    padding: 12px 15px;
    font-size: 14px;
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
  
  .nav-btn {
    padding: 5px 10px;
    font-size: 11px;
  }
  
  .edit-container {
    margin-top: 65px;
    padding: 15px 10px;
  }
  
  .edit-card {
    padding: 20px 15px;
    border-radius: 12px;
  }
  
  .card-header h2 {
    font-size: 18px;
  }
  
  .avatar-upload {
    width: 80px;
    height: 80px;
  }
  
  .form-item {
    margin-bottom: 18px;
  }
  
  .form-item label {
    font-size: 12px;
  }
  
  .form-item input,
  .form-item textarea,
  .form-item select {
    padding: 10px 12px;
    font-size: 14px;
    border-radius: 10px;
  }
  
  .submit-btn {
    padding: 12px;
    font-size: 14px;
  }
}
</style>
