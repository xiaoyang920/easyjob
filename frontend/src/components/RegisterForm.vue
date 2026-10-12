<template>
  <div class="register-form">
    <h2 class="form-title">注册</h2>

    <el-form
      :model="formData"
      :rules="rules"
      ref="formRef"
      label-width="0"
    >
      <el-form-item prop="nickName">
        <el-input
          v-model="formData.nickName"
          placeholder="请输入昵称"
          size="large"
          maxlength="20"
          clearable
        >
          <template #prefix>
            <el-icon><User /></el-icon>
          </template>
        </el-input>
      </el-form-item>

      <el-form-item prop="email">
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

      <!-- 新增：验证码输入框 -->
      <el-form-item prop="code">
        <div style="display: flex; gap: 10px;">
          <el-input
            v-model="formData.code"
            placeholder="请输入邮箱验证码"
            size="large"
            maxlength="6"
            clearable
          >
            <template #prefix>
              <el-icon><Message /></el-icon>
            </template>
          </el-input>
          <el-button
            size="large"
            :disabled="countdown > 0 || !formData.email"
            @click="sendCode"
            style="min-width: 120px;"
          >
            {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
          </el-button>
        </div>
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

      <el-form-item prop="confirmPassword">
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

    <div class="form-footer">
      <span>已有账号？</span>
      <a @click="emit('switchToLogin')">立即登录</a>
    </div>

    <!-- 装饰图片 -->
    <div class="decoration-image"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { acceptAuthSession } from '@/utils/authSession'

const emit = defineEmits(['success', 'switchToLogin'])

// 表单数据
const formData = reactive({
  nickName: '',
  email: '',
  code: '', // 新增：验证码
  password: '',
  confirmPassword: ''
})

// 表单引用
const formRef = ref()

// 状态
const loading = ref(false)
const countdown = ref(0) // 新增：倒计时
let timer: number | null = null // 新增：定时器
onUnmounted(() => { if (timer) clearInterval(timer) })

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
    { min: 2, max: 20, message: '昵称长度在2到20个字符', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码为6位数字', trigger: 'blur' }
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

// 新增：发送验证码
async function sendCode() {
  // 校验邮箱格式
  if (!formData.email || !/^[a-zA-Z0-9_-]+@[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)+$/.test(formData.email)) {
    ElMessage.warning('请先输入正确的邮箱地址')
    return
  }

  try {
    const response = await request.post('/auth/send-code', { email: formData.email })
    if (response.status === 'success' || response.code === 200) {
      ElMessage.success('验证码已发送，请查收邮件')
      // 开始倒计时
      countdown.value = 60
      timer = setInterval(() => {
        countdown.value--
        if (countdown.value <= 0 && timer) {
          clearInterval(timer)
          timer = null
        }
      }, 1000)
    } else {
      ElMessage.error(response.message || '发送失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '发送失败，请稍后重试')
  }
}

// 注册处理
async function handleRegister() {
  if (!formRef.value || loading.value) return

  await formRef.value.validate(async (valid: boolean) => {
    if (!valid || loading.value) return

    loading.value = true

    try {
      const { confirmPassword, ...registerData } = formData
      const response = await request.post('/auth/register', registerData)

      if (response.status === 'success' || response.code === 200) {
        acceptAuthSession(response.data)
        emit('success')
      } else {
        ElMessage.error(response.message || '注册失败')
      }
    } catch (error: any) {
      ElMessage.error(error.message || '注册失败，请稍后重试')
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.register-form {
  padding: 40px 35px 30px;
  position: relative;
  overflow: hidden;
}

.form-title {
  text-align: center;
  font-size: 26px;
  font-weight: 700;
  color: var(--ej-ink);
  margin-bottom: 35px;
  letter-spacing: 2px;
}

.register-form :deep(.el-form-item) {
  margin-bottom: 22px;
}

.register-form :deep(.el-input__wrapper) {
  padding: 0 16px;
  height: 52px;
  background: var(--ej-canvas) !important;
  border: 1px solid var(--ej-line);
  box-shadow: none !important;
  border-radius: 14px;
  transition: all 0.25s ease;
}

.register-form :deep(.el-input__wrapper:hover) {
  border-color: var(--ej-ink);
  background: var(--ej-surface) !important;
}

.register-form :deep(.el-input__wrapper.is-focus) {
  background: var(--ej-surface) !important;
  border-color: var(--ej-ink);
  box-shadow: 3px 3px 0 #11110f14 !important;
}

/* 彻底清除输入框内部蓝色 */
.register-form :deep(.el-input__inner) {
  color: var(--ej-ink);
  font-size: 15px;
  height: 100%;
  background: transparent !important;
  box-shadow: none !important;
}

.register-form :deep(.el-input) {
  --el-input-focus-border-color: var(--ej-accent);
  --el-input-bg-color: transparent;
}

.register-form :deep(.el-input__inner:focus) {
  background: transparent !important;
  box-shadow: none !important;
}

.register-form :deep(.el-input__inner::placeholder) {
  color: var(--ej-muted);
  font-size: 14px;
}

.register-form :deep(.el-input__prefix) {
  color: var(--ej-muted);
  font-size: 18px;
}

.register-form :deep(.el-button--primary) {
  background: var(--ej-accent);
  border-color: var(--ej-accent);
  height: 52px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 14px;
  transition: all 0.25s ease;
}

.register-form :deep(.el-button--primary:hover) {
  background: var(--ej-ink);
  border-color: var(--ej-ink);
}

/* 按下时收起偏移阴影，形成“压下去”的反馈 */
.register-form :deep(.el-button--primary:active) {
  background: var(--studio-lime);
  color: var(--ej-ink);
  box-shadow: 1px 1px 0 var(--ej-ink);
  transform: translateY(0);
}

.register-form :deep(.el-button--primary.is-disabled) {
  background: var(--ej-soft);
  border-color: var(--ej-line);
  color: var(--ej-muted);
}

/* 获取验证码按钮 */
.register-form :deep(.el-button--default) {
  background: var(--ej-surface);
  border: 1px solid var(--ej-ink);
  color: var(--ej-ink);
}

.register-form :deep(.el-button--default:hover:not(.is-disabled)) {
  background: var(--studio-lime);
  border-color: var(--ej-ink);
  color: var(--ej-ink);
}

.register-form :deep(.el-button--default.is-disabled) {
  background: var(--ej-canvas);
  border-color: var(--ej-line);
  color: var(--ej-muted);
}

.form-footer {
  text-align: center;
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid var(--ej-hairline);
  color: var(--ej-muted);
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
  .register-form {
    padding: 20px 15px 15px;
  }
  
  .form-title {
    font-size: 20px;
    margin-bottom: 20px;
    letter-spacing: 1px;
  }
  
  .register-form :deep(.el-form-item) {
    margin-bottom: 12px;
  }
  
  .register-form :deep(.el-input__wrapper) {
    padding: 0 10px;
    height: 38px;
    border-radius: 10px;
  }
  
  .register-form :deep(.el-input__inner) {
    font-size: 13px;
  }
  
  .register-form :deep(.el-input__inner::placeholder) {
    font-size: 12px;
  }
  
  .register-form :deep(.el-input__prefix) {
    font-size: 16px;
  }
  
  .register-form :deep(.el-button--primary) {
    height: 38px;
    font-size: 13px;
    border-radius: 10px;
  }
  
  .register-form :deep(.el-button--default) {
    height: 38px;
    font-size: 11px;
    min-width: 90px !important;
    padding: 0 8px;
  }
  
  .form-footer {
    margin-top: 15px;
    padding-top: 15px;
    font-size: 12px;
  }
  
  .decoration-image {
    width: 80px;
    height: 80px;
    bottom: -5px;
    right: -10px;
  }
}
</style>
