<template>
  <div class="login-form">
    <h2 class="form-title">登录</h2>
    
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

          <el-form-item>
            <el-button
              type="primary"
              size="large"
              style="width: 100%"
              :loading="loading"
              @click="handleLogin"
            >
              登录
            </el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="邮箱验证码登录" name="code">
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
                :disabled="codeSending || countdown > 0"
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

    <div class="form-footer">
      <span>还没有账号？</span>
      <a @click="emit('switchToRegister')">立即注册</a>
    </div>

    <!-- 装饰图片 -->
    <div class="decoration-image"></div>
  </div>
</template>

<script setup lang="ts">
import { clearAccountStorage } from '@/utils/searchHistory'
import { eventBus, EVENT_AUTH_CHANGED } from '@/utils/eventBus'
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

const emit = defineEmits(['success', 'switchToRegister'])

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
    { required: true, message: '请输入密码', trigger: 'blur' }
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

// 密码登录
async function handleLogin() {
  if (!passwordFormRef.value) return
  
  await passwordFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return
    
    loading.value = true
    
    try {
      const response = await request.post('/auth/login', formData)
      
      // 兼容多种响应格式
      if (response.status === 'success' || response.code === 200) {
        clearAccountStorage()
        
        const data = response.data || response
        localStorage.setItem('token', data.token)
        localStorage.setItem('userId', data.userId)
        localStorage.setItem('email', data.email)
        localStorage.setItem('nickName', data.nickName || '')
        localStorage.setItem('avatar', data.avatar || '')
        eventBus.emit(EVENT_AUTH_CHANGED)
        
        emit('success')
      } else {
        ElMessage.error(response.message || '登录失败')
      }
    } catch (error: any) {
      ElMessage.error(error.message || '登录失败，请稍后重试')
    } finally {
      loading.value = false
    }
  })
}

// 发送验证码
async function sendVerificationCode() {
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
    }, {
      timeout: 30000  // 发送邮件耗时较长，设置30秒超时
    })
    
    
    // 兼容多种响应格式
    if (response.code === 200 || response.status === 'success') {
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
  } catch (error: any) {
    ElMessage.error(error.message || '发送失败，请稍后重试')
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
    
    loading.value = true
    
    try {
      const response = await request.post('/auth/login-by-email', codeFormData)
      
      // 兼容多种响应格式
      if (response.status === 'success' || response.code === 200) {
        clearAccountStorage()
        
        const data = response.data || response
        localStorage.setItem('token', data.token)
        localStorage.setItem('userId', data.userId)
        localStorage.setItem('email', data.email)
        localStorage.setItem('nickName', data.nickName || '')
        localStorage.setItem('avatar', data.avatar || '')
        eventBus.emit(EVENT_AUTH_CHANGED)
        
        if (countdownTimer) {
          clearInterval(countdownTimer)
          countdownTimer = null
        }
        
        emit('success')
      } else {
        ElMessage.error(response.message || '验证码错误或已过期')
      }
    } catch (error: any) {
      ElMessage.error(error.message || '登录失败，请稍后重试')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-form {
  padding: 40px 35px 30px;
  position: relative;
  overflow: hidden;
}

.form-title {
  text-align: center;
  font-size: 26px;
  font-weight: 700;
  color: #1a1a1a;
  margin-bottom: 35px;
  letter-spacing: 2px;
}

.login-tabs {
  margin-bottom: 10px;
}

.login-tabs :deep(.el-tabs__header) {
  margin-bottom: 28px;
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.login-tabs :deep(.el-tabs__nav) {
  display: flex;
  gap: 30px;
}

.login-tabs :deep(.el-tabs__item) {
  font-size: 15px;
  font-weight: 500;
  color: #9ca3af;
  padding: 0;
  height: 36px;
  line-height: 36px;
  transition: all 0.3s ease;
}

.login-tabs :deep(.el-tabs__item:hover) {
  color: #4b5563;
}

.login-tabs :deep(.el-tabs__item.is-active) {
  color: #1f2937;
  font-weight: 600;
}

.login-tabs :deep(.el-tabs__active-bar) {
  height: 2px;
  background: var(--ej-accent);
  border-radius: 2px;
}

.login-tabs :deep(.el-form-item) {
  margin-bottom: 22px;
}

.login-tabs :deep(.el-input__wrapper) {
  padding: 0 16px;
  height: 52px;
  background: var(--ej-canvas) !important;
  border: 1px solid var(--ej-line);
  box-shadow: none !important;
  border-radius: 14px;
  transition: all 0.25s ease;
}

.login-tabs :deep(.el-input__wrapper:hover) {
  border-color: var(--ej-ink);
  background: var(--ej-surface) !important;
}

.login-tabs :deep(.el-input__wrapper.is-focus) {
  background: var(--ej-surface) !important;
  border-color: var(--ej-ink);
  box-shadow: 3px 3px 0 #11110f14 !important;
}

/* 彻底清除输入框内部蓝色 */
.login-tabs :deep(.el-input__inner) {
  color: #1f2937;
  font-size: 15px;
  height: 100%;
  background: transparent !important;
  box-shadow: none !important;
}

.login-tabs :deep(.el-input) {
  --el-input-focus-border-color: var(--ej-accent);
  --el-input-bg-color: transparent;
}

.login-tabs :deep(.el-input__inner:focus) {
  background: transparent !important;
  box-shadow: none !important;
}

.login-tabs :deep(.el-input__inner::placeholder) {
  color: #9ca3af;
  font-size: 14px;
}

.login-tabs :deep(.el-input__prefix) {
  color: #9ca3af;
  font-size: 18px;
}

.login-tabs :deep(.el-button) {
  font-size: 15px;
  font-weight: 600;
  border-radius: 14px;
  transition: all 0.25s ease;
}

.login-tabs :deep(.el-button--primary) {
  background: var(--ej-accent);
  border-color: var(--ej-accent);
  height: 52px;
}

.login-tabs :deep(.el-button--primary:hover) {
  background: var(--ej-ink);
  border-color: var(--ej-ink);
}

.login-tabs :deep(.el-button--primary:active) {
  background: #0093c4;
}

.login-tabs :deep(.el-button--primary.is-disabled) {
  background: #99d6ed;
  border-color: #99d6ed;
}

.login-tabs :deep(.el-button--default) {
  background: var(--ej-surface);
  border: 1px solid var(--ej-ink);
  color: #4b5563;
  height: 52px;
}

.login-tabs :deep(.el-button--default:hover) {
  background: #fff;
  border-color: var(--ej-accent);
  color: var(--ej-accent);
}

.login-tabs :deep(.el-button--success) {
  background: #f0fff4;
  border: 1.5px solid #52c41a;
  color: #52c41a;
  height: 52px;
}

.form-footer {
  text-align: center;
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid #f1f5f9;
  color: #6b7280;
  font-size: 14px;
  position: relative;
  z-index: 1;
}

.form-footer a {
  color: var(--ej-accent);
  cursor: pointer;
  margin-left: 6px;
  text-decoration: none;
  font-weight: 600;
  transition: color 0.2s;
}

.form-footer a:hover {
  color: var(--ej-ink);
}

/* 装饰图片 */
.decoration-image {
  position: absolute;
  bottom: -10px;
  right: -20px;
  width: 140px;
  height: 140px;
  background-image: url('/images/login-decoration.jpg');
  background-size: cover;
  background-position: center;
  opacity: 0.12;
  pointer-events: none;
  z-index: 0;
  border-radius: 50%;
  filter: saturate(0.8);
}

/* 移动端适配 */
@media (max-width: 480px) {
  .login-form {
    padding: 20px 15px 15px;
  }
  
  .form-title {
    font-size: 20px;
    margin-bottom: 20px;
    letter-spacing: 1px;
  }
  
  .login-tabs :deep(.el-tabs__header) {
    margin-bottom: 15px;
  }
  
  .login-tabs :deep(.el-tabs__nav) {
    gap: 15px;
  }
  
  .login-tabs :deep(.el-tabs__item) {
    font-size: 13px;
    height: 30px;
    line-height: 30px;
  }
  
  .login-tabs :deep(.el-form-item) {
    margin-bottom: 12px;
  }
  
  .login-tabs :deep(.el-input__wrapper) {
    padding: 0 10px;
    height: 40px;
    border-radius: 10px;
  }
  
  .login-tabs :deep(.el-input__inner) {
    font-size: 13px;
  }
  
  .login-tabs :deep(.el-input__inner::placeholder) {
    font-size: 12px;
  }
  
  .login-tabs :deep(.el-input__prefix) {
    font-size: 16px;
  }
  
  .login-tabs :deep(.el-button) {
    font-size: 13px;
    border-radius: 10px;
  }
  
  .login-tabs :deep(.el-button--primary) {
    height: 40px;
  }
  
  .login-tabs :deep(.el-button--default) {
    height: 40px;
    font-size: 12px;
    padding: 0 10px;
  }
  
  .form-footer {
    margin-top: 15px;
    padding-top: 15px;
    font-size: 12px;
  }
  
  .decoration-image {
    width: 100px;
    height: 100px;
    bottom: -5px;
    right: -10px;
  }
}
</style>
