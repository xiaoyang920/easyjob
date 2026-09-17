<template>
  <div class="login-page">
    <div class="login-container">
      <el-card class="login-card">
        <template #header>
          <div class="card-header">
            <h2>用户登录</h2>
          </div>
        </template>

        <!-- 登录方式切换 -->
        <el-tabs v-model="loginMode" class="login-tabs">
          <el-tab-pane label="密码登录" name="password">
            <el-form :model="formData" :rules="passwordRules" ref="passwordFormRef" label-width="0">
              <el-form-item prop="email">
                <el-input
                  v-model="formData.email"
                  placeholder="请输入邮箱"
                  size="large"
                  clearable
                >
                  <template #prefix>
                    <el-icon><Message /></el-icon>
                  </template>
                </el-input>
              </el-form-item>

              <el-form-item prop="password">
                <el-input
                  v-model="formData.password"
                  type="password"
                  placeholder="请输入密码"
                  size="large"
                  show-password
                  clearable
                >
                  <template #prefix>
                    <el-icon><Lock /></el-icon>
                  </template>
                </el-input>
              </el-form-item>

              <!-- 腾讯云验证码 -->
              <el-form-item>
                <el-button
                  type="info"
                  :plain="!captchaVerified"
                  :class="{ 'captcha-success': captchaVerified }"
                  style="width: 100%"
                  @click="showTencentCaptcha"
                >
                  <el-icon v-if="!captchaVerified"><Grid /></el-icon>
                  <el-icon v-else><CircleCheck /></el-icon>
                  <span style="margin-left: 8px">{{ captchaVerified ? '验证已完成' : '点击完成验证' }}</span>
                </el-button>
              </el-form-item>

              <el-form-item>
                <el-button
                  type="primary"
                  size="large"
                  style="width: 100%"
                  :loading="loading"
                  :disabled="!captchaVerified"
                  @click="handleLogin"
                >
                  登录
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="验证码登录" name="code">
            <el-form :model="codeFormData" :rules="codeRules" ref="codeFormRef" label-width="0">
              <el-form-item prop="email">
                <el-input
                  v-model="codeFormData.email"
                  placeholder="请输入邮箱"
                  size="large"
                  clearable
                >
                  <template #prefix>
                    <el-icon><Message /></el-icon>
                  </template>
                </el-input>
              </el-form-item>

              <!-- 腾讯云验证码 (验证码登录也需要) -->
              <el-form-item>
                <el-button
                  type="info"
                  :plain="!captchaVerified"
                  :class="{ 'captcha-success': captchaVerified }"
                  style="width: 100%"
                  @click="showTencentCaptcha"
                >
                  <el-icon v-if="!captchaVerified"><Grid /></el-icon>
                  <el-icon v-else><CircleCheck /></el-icon>
                  <span style="margin-left: 8px">{{ captchaVerified ? '验证已完成' : '点击完成验证' }}</span>
                </el-button>
              </el-form-item>

              <el-form-item prop="code">
                <div style="display: flex; gap: 10px; width: 100%">
                  <el-input
                    v-model="codeFormData.code"
                    placeholder="请输入6位验证码"
                    size="large"
                    maxlength="6"
                    clearable
                    style="flex: 1"
                  >
                    <template #prefix>
                      <el-icon><Key /></el-icon>
                    </template>
                  </el-input>
                  <el-button
                    size="large"
                    :disabled="codeSending || countdown > 0 || !captchaVerified"
                    @click="sendVerificationCode"
                  >
                    {{ codeButtonText }}
                  </el-button>
                </div>
              </el-form-item>

              <el-form-item>
                <el-button
                  type="primary"
                  size="large"
                  style="width: 100%"
                  :loading="loading"
                  @click="handleCodeLogin"
                >
                  登录
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>

        <div class="login-footer">
          <span>还没有账号？</span>
          <router-link to="/register">立即注册</router-link>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

const router = useRouter()

// 登录模式
const loginMode = ref('password')

// 密码登录表单
const formData = reactive({
  email: '',
  password: ''
})

// 验证码登录表单
const codeFormData = reactive({
  email: '',
  code: ''
})

// 表单引用
const passwordFormRef = ref()
const codeFormRef = ref()

// 验证规则
const passwordRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

const codeRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码为6位数字', trigger: 'blur' }
  ]
}

// 状态
const loading = ref(false)
const codeSending = ref(false)
const countdown = ref(0)
const codeButtonText = ref('获取验证码')
let countdownTimer: number | null = null

// 腾讯云验证码
const captchaVerified = ref(false)
const captchaTicket = ref('')
const captchaRandstr = ref('')
const TENCENT_CAPTCHA_APP_ID = '194862106'

// 检查登录状态
onMounted(() => {
  const token = localStorage.getItem('token')
  if (token) {
    router.push('/')
  }
})

// 显示腾讯云验证码
function showTencentCaptcha() {
  // @ts-ignore
  const captcha = new TencentCaptcha(TENCENT_CAPTCHA_APP_ID, (res: any) => {
    if (res.ret === 0) {
      captchaVerified.value = true
      captchaTicket.value = res.ticket
      captchaRandstr.value = res.randstr
      ElMessage.success('验证成功')
    } else {
      captchaVerified.value = false
      captchaTicket.value = ''
      captchaRandstr.value = ''
    }
  })
  captcha.show()
}

// 密码登录
async function handleLogin() {
  if (!passwordFormRef.value) return
  
  await passwordFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return
    
    if (!captchaVerified.value) {
      ElMessage.warning('请先完成人机验证')
      return
    }
    
    loading.value = true
    
    try {
      const response = await request.post('/auth/login', formData)
      
      if (response.status === 'success') {
        ElMessage.success('登录成功')
        
        localStorage.clear()
        localStorage.setItem('token', response.data.token)
        localStorage.setItem('userId', response.data.userId)
        localStorage.setItem('email', response.data.email)
        localStorage.setItem('nickName', response.data.nickName)
        localStorage.setItem('avatar', response.data.avatar || '')
        
        setTimeout(() => {
          router.push('/')
        }, 500)
      } else {
        ElMessage.error(response.message || '登录失败')
      }
    } catch (error) {
      console.error('登录失败:', error)
      ElMessage.error('登录失败，请稍后重试')
    } finally {
      loading.value = false
    }
  })
}

// 发送验证码
async function sendVerificationCode() {
  if (!captchaVerified.value) {
    ElMessage.warning('请先完成人机验证')
    return
  }
  
  if (!codeFormData.email) {
    ElMessage.warning('请输入邮箱地址')
    return
  }
  
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRegex.test(codeFormData.email)) {
    ElMessage.warning('请输入正确的邮箱地址')
    return
  }
  
  codeSending.value = true
  codeButtonText.value = '发送中...'
  
  try {
    const response = await request.post('/auth/send-code', {
      email: codeFormData.email
    })
    
    if (response.code === 200) {
      countdown.value = 60
      codeButtonText.value = `${countdown.value}s`
      
      countdownTimer = window.setInterval(() => {
        countdown.value--
        if (countdown.value > 0) {
          codeButtonText.value = `${countdown.value}s`
        } else {
          codeButtonText.value = '重新发送'
          if (countdownTimer) {
            clearInterval(countdownTimer)
            countdownTimer = null
          }
        }
      }, 1000)
      
      ElMessage.success('验证码已发送，请查收邮件')
    } else {
      ElMessage.error(response.message || '发送失败')
      codeButtonText.value = '获取验证码'
    }
  } catch (error) {
    console.error('发送验证码失败:', error)
    ElMessage.error('发送失败，请稍后重试')
    codeButtonText.value = '获取验证码'
  } finally {
    codeSending.value = false
  }
}

// 验证码登录
async function handleCodeLogin() {
  if (!codeFormRef.value) return
  
  await codeFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return
    
    if (!captchaVerified.value) {
      ElMessage.warning('请先完成人机验证')
      return
    }
    
    loading.value = true
    
    try {
      const response = await request.post('/auth/login-by-email', codeFormData)
      
      if (response.code === 200) {
        ElMessage.success('登录成功')
        
        localStorage.clear()
        localStorage.setItem('token', response.data.token)
        localStorage.setItem('userId', response.data.userId)
        localStorage.setItem('email', response.data.email)
        localStorage.setItem('nickName', response.data.nickName)
        localStorage.setItem('avatar', response.data.avatar || '')
        
        if (countdownTimer) {
          clearInterval(countdownTimer)
          countdownTimer = null
        }
        
        setTimeout(() => {
          router.push('/')
        }, 500)
      } else {
        ElMessage.error(response.message || '验证码错误或已过期')
      }
    } catch (error) {
      console.error('登录失败:', error)
      ElMessage.error('登录失败，请稍后重试')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.login-page::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.1) 1px, transparent 1px);
  background-size: 50px 50px;
  animation: backgroundMove 20s linear infinite;
}

@keyframes backgroundMove {
  0% {
    transform: translate(0, 0);
  }
  100% {
    transform: translate(50px, 50px);
  }
}

.login-container {
  width: 100%;
  max-width: 400px;
  padding: 15px;
  position: relative;
  z-index: 1;
  animation: slideUp 0.6s ease-out;
  box-sizing: border-box;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.login-card {
  border-radius: 20px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  overflow: hidden;
  transition: all 0.3s ease;
}

.login-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 25px 70px rgba(0, 0, 0, 0.4);
}

.login-card :deep(.el-card__header) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(255, 255, 255, 0.9) 100%);
  border-bottom: none;
  padding: 30px 20px 20px;
}

.login-card :deep(.el-card__body) {
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
}

.card-header {
  text-align: center;
}

.card-header h2 {
  margin: 0;
  font-size: 28px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.login-tabs {
  margin-top: 20px;
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 0;
}

.login-tabs :deep(.el-tabs__active-bar) {
  height: 3px;
  border-radius: 3px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 500;
  transition: all 0.3s;
}

.login-tabs :deep(.el-tabs__item:hover) {
  color: #667eea;
}

.login-tabs :deep(.el-tabs__item.is-active) {
  color: #667eea;
  font-weight: 600;
}

.login-tabs :deep(.el-form-item) {
  margin-bottom: 24px;
  animation: fadeIn 0.5s ease-out;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateX(-10px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.login-tabs :deep(.el-input__wrapper) {
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  transition: all 0.3s;
}

.login-tabs :deep(.el-input__wrapper:hover) {
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
}

.login-tabs :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 4px 16px rgba(102, 126, 234, 0.25);
  border-color: #667eea;
}

.login-tabs :deep(.el-button) {
  border-radius: 12px;
  font-weight: 500;
  transition: all 0.3s;
}

.login-tabs :deep(.el-button--primary) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}

.login-tabs :deep(.el-button--primary:hover) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
}

.login-tabs :deep(.el-button--primary:active) {
  transform: translateY(0);
}

.captcha-success {
  background: linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%) !important;
  border-color: #67c23a !important;
  color: #67c23a !important;
  animation: successPulse 0.5s ease-out;
}

@keyframes successPulse {
  0% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.05);
  }
  100% {
    transform: scale(1);
  }
}

.login-footer {
  text-align: center;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  color: #909399;
  font-size: 14px;
}

.login-footer a {
  color: #667eea;
  text-decoration: none;
  margin-left: 5px;
  font-weight: 500;
  transition: all 0.3s;
  position: relative;
}

.login-footer a::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  width: 0;
  height: 2px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  transition: width 0.3s;
}

.login-footer a:hover {
  color: #764ba2;
}

.login-footer a:hover::after {
  width: 100%;
}

/* 响应式 */
@media (max-width: 768px) {
  .login-container {
    max-width: 100%;
    padding: 15px;
    box-sizing: border-box;
  }
  
  .login-card {
    border-radius: 15px;
    width: 100%;
  }
  
  .login-card :deep(.el-card__header) {
    padding: 20px 15px 15px;
  }
  
  .login-card :deep(.el-card__body) {
    padding: 20px 15px;
  }
  
  .card-header h2 {
    font-size: 24px;
  }
  
  .login-tabs :deep(.el-tabs__item) {
    font-size: 14px;
    padding: 0 15px;
  }
  
  .login-tabs :deep(.el-form-item) {
    margin-bottom: 18px;
  }
  
  .login-tabs :deep(.el-input__inner) {
    font-size: 14px;
  }
  
  .login-tabs :deep(.el-button) {
    font-size: 14px;
  }
  
  .login-footer {
    margin-top: 18px;
    padding-top: 18px;
    font-size: 13px;
  }
}

@media (max-width: 480px) {
  .login-page {
    padding: 10px;
    overflow-x: hidden;
  }
  
  .login-container {
    max-width: 100%;
    width: 100%;
    padding: 8px;
    box-sizing: border-box;
    margin: 0 auto;
  }
  
  .login-card {
    border-radius: 10px;
    width: 100%;
    max-width: 100%;
    margin: 0;
    box-sizing: border-box;
  }
  
  .login-card :deep(.el-card__header) {
    padding: 12px 10px 10px;
  }
  
  .login-card :deep(.el-card__body) {
    padding: 12px 10px;
  }
  
  .card-header h2 {
    font-size: 18px;
  }
  
  .login-tabs :deep(.el-tabs__header) {
    margin-bottom: 12px;
  }
  
  .login-tabs :deep(.el-tabs__item) {
    font-size: 13px;
    padding: 0 8px;
    height: 36px;
    line-height: 36px;
  }
  
  .login-tabs :deep(.el-form-item) {
    margin-bottom: 12px;
  }
  
  .login-tabs :deep(.el-input) {
    --el-input-height: 36px;
  }
  
  .login-tabs :deep(.el-input__wrapper) {
    border-radius: 6px;
    padding: 0 10px;
  }
  
  .login-tabs :deep(.el-input__inner) {
    font-size: 13px;
  }
  
  .login-tabs :deep(.el-button) {
    border-radius: 6px;
    font-size: 13px;
    height: 36px;
  }
  
  .login-footer {
    margin-top: 12px;
    padding-top: 12px;
    font-size: 12px;
  }
}
</style>
