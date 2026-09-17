<template>
  <div class="register-page">
    <div class="register-container">
      <el-card class="register-card">
        <template #header>
          <div class="card-header">
            <h2>用户注册</h2>
            <p>开启你的创作之旅</p>
          </div>
        </template>

        <el-form
          :model="formData"
          :rules="rules"
          ref="formRef"
          label-width="80px"
        >
          <el-form-item label="昵称" prop="nickName">
            <el-input
              v-model="formData.nickName"
              placeholder="请输入昵称（2-20个字符）"
              size="large"
              maxlength="20"
              show-word-limit
              clearable
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item label="邮箱" prop="email">
            <el-input
              v-model="formData.email"
              placeholder="请输入邮箱地址"
              size="large"
              clearable
            >
              <template #prefix>
                <el-icon><Message /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="formData.password"
              type="password"
              placeholder="请输入密码（至少6位）"
              size="large"
              show-password
              clearable
            >
              <template #prefix>
                <el-icon><Lock /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item label="确认密码" prop="confirmPassword">
            <el-input
              v-model="formData.confirmPassword"
              type="password"
              placeholder="请再次输入密码"
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
              @click="handleRegister"
            >
              注册
            </el-button>
          </el-form-item>
        </el-form>

        <div class="register-footer">
          <span>已有账号？</span>
          <router-link to="/login">立即登录</router-link>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'

const router = useRouter()

// 表单数据
const formData = reactive({
  nickName: '',
  email: '',
  password: '',
  confirmPassword: ''
})

// 表单引用
const formRef = ref()

// 状态
const loading = ref(false)

// 验证规则
const validatePass = (rule: any, value: any, callback: any) => {
  if (value === '') {
    callback(new Error('请再次输入密码'))
  } else if (value !== formData.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  nickName: [
    { required: true, message: '请输入昵称', trigger: 'blur' },
    { min: 2, max: 20, message: '昵称长度在 2 到 20 个字符', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validatePass, trigger: 'blur' }
  ]
}

// 注册处理
async function handleRegister() {
  if (!formRef.value) return

  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return

    loading.value = true

    try {
      const { confirmPassword, ...registerData } = formData
      const response = await request.post('/auth/register', registerData)

      if (response.status === 'success' || response.code === 200) {
        ElMessage.success('注册成功，即将跳转到登录页面')
        setTimeout(() => {
          router.push('/login')
        }, 1500)
      } else {
        ElMessage.error(response.message || '注册失败')
      }
    } catch (error: any) {
      console.error('注册失败:', error)
      ElMessage.error(error.response?.data?.message || '注册失败，请稍后重试')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.register-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.register-page::before {
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

.register-container {
  width: 100%;
  max-width: 420px;
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

.register-card {
  border-radius: 20px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  overflow: hidden;
  transition: all 0.3s ease;
}

.register-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 25px 70px rgba(0, 0, 0, 0.4);
}

.register-card :deep(.el-card__header) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(255, 255, 255, 0.9) 100%);
  border-bottom: none;
  padding: 30px 20px 20px;
}

.register-card :deep(.el-card__body) {
  padding: 30px;
  background: rgba(255, 255, 255, 0.95);
}

.card-header {
  text-align: center;
}

.card-header h2 {
  margin: 0 0 8px 0;
  font-size: 28px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.card-header p {
  margin: 0;
  font-size: 14px;
  color: #909399;
}

.register-card :deep(.el-form-item) {
  margin-bottom: 24px;
  animation: fadeIn 0.5s ease-out;
  animation-fill-mode: both;
}

.register-card :deep(.el-form-item:nth-child(1)) {
  animation-delay: 0.1s;
}

.register-card :deep(.el-form-item:nth-child(2)) {
  animation-delay: 0.2s;
}

.register-card :deep(.el-form-item:nth-child(3)) {
  animation-delay: 0.3s;
}

.register-card :deep(.el-form-item:nth-child(4)) {
  animation-delay: 0.4s;
}

.register-card :deep(.el-form-item:nth-child(5)) {
  animation-delay: 0.5s;
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

.register-card :deep(.el-form-item__label) {
  font-weight: 500;
  color: #606266;
}

.register-card :deep(.el-input__wrapper) {
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
  transition: all 0.3s;
}

.register-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
}

.register-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 4px 16px rgba(102, 126, 234, 0.25);
  border-color: #667eea;
}

.register-card :deep(.el-button) {
  border-radius: 12px;
  font-weight: 500;
  transition: all 0.3s;
}

.register-card :deep(.el-button--primary) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}

.register-card :deep(.el-button--primary:hover) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
}

.register-card :deep(.el-button--primary:active) {
  transform: translateY(0);
}

.register-footer {
  text-align: center;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  color: #909399;
  font-size: 14px;
}

.register-footer a {
  color: #667eea;
  text-decoration: none;
  margin-left: 5px;
  font-weight: 500;
  transition: all 0.3s;
  position: relative;
}

.register-footer a::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  width: 0;
  height: 2px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  transition: width 0.3s;
}

.register-footer a:hover {
  color: #764ba2;
}

.register-footer a:hover::after {
  width: 100%;
}

/* 响应式 */
@media (max-width: 768px) {
  .register-container {
    max-width: 100%;
    padding: 15px;
    box-sizing: border-box;
  }
  
  .register-card {
    border-radius: 15px;
    width: 100%;
  }
  
  .register-card :deep(.el-card__header) {
    padding: 20px 15px 15px;
  }
  
  .register-card :deep(.el-card__body) {
    padding: 20px 15px;
  }
  
  .card-header h2 {
    font-size: 24px;
  }
  
  .card-header p {
    font-size: 13px;
  }
  
  .register-card :deep(.el-form-item) {
    margin-bottom: 18px;
  }
  
  .register-card :deep(.el-form-item__label) {
    font-size: 13px;
  }
  
  .register-card :deep(.el-input__inner) {
    font-size: 14px;
  }
  
  .register-footer {
    margin-top: 18px;
    padding-top: 18px;
    font-size: 13px;
  }
}

@media (max-width: 480px) {
  .register-page {
    padding: 10px;
    overflow-x: hidden;
  }
  
  .register-container {
    max-width: 100%;
    width: 100%;
    padding: 8px;
    box-sizing: border-box;
    margin: 0 auto;
  }
  
  .register-card {
    border-radius: 10px;
    width: 100%;
    max-width: 100%;
    margin: 0;
    box-sizing: border-box;
  }
  
  .register-card :deep(.el-card__header) {
    padding: 12px 10px 8px;
  }
  
  .register-card :deep(.el-card__body) {
    padding: 10px;
  }
  
  .card-header h2 {
    font-size: 18px;
  }
  
  .card-header p {
    font-size: 11px;
    margin-top: 4px;
  }
  
  .register-card :deep(.el-form) {
    /* 移动端表单标签垂直排列 */
  }
  
  .register-card :deep(.el-form-item) {
    margin-bottom: 10px;
    flex-direction: column;
  }
  
  .register-card :deep(.el-form-item__label) {
    text-align: left !important;
    padding-bottom: 3px;
    font-size: 12px;
    line-height: 1.2;
  }
  
  .register-card :deep(.el-form-item__content) {
    margin-left: 0 !important;
  }
  
  .register-card :deep(.el-input) {
    --el-input-height: 34px;
  }
  
  .register-card :deep(.el-input__wrapper) {
    border-radius: 6px;
    padding: 0 8px;
  }
  
  .register-card :deep(.el-input__inner) {
    font-size: 13px;
  }
  
  .register-card :deep(.el-button) {
    border-radius: 6px;
    font-size: 13px;
    height: 34px;
  }
  
  .register-footer {
    margin-top: 10px;
    padding-top: 10px;
    font-size: 12px;
  }
}
</style>
