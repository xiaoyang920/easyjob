import axios from 'axios'
import { eventBus, EVENT_AUTH_EXPIRED } from './eventBus'

// 防止多个并发请求同时401时重复触发登录过期事件
let isAuthExpiredEmitted = false

function emitAuthExpired() {
  if (isAuthExpiredEmitted) return
  isAuthExpiredEmitted = true
  localStorage.clear()
  eventBus.emit(EVENT_AUTH_EXPIRED)
  // 延迟重置标记，允许后续新的401触发（如用户重新登录后再次过期）
  setTimeout(() => {
    isAuthExpiredEmitted = false
  }, 3000)
}

const request = axios.create({
  // 无论是开发还是生产，统一使用 /api 前缀
  // 生产环境下，它会请求 http://你的服务器IP/api/... 并由 Nginx 转发到 8080
  baseURL: '/api', 
  timeout: 10000
})

// 请求拦截器 - 自动添加token
request.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 统一处理错误
request.interceptors.response.use(
  response => {
    const res = response.data
    
    // 如果后端返回的 code 不是 200/success，视为业务错误
    if (res.code && res.code !== 200 && res.status !== 'success') {
      // token过期：清除本地存储并通知UI弹出登录弹窗
      if (res.code === 401) {
        emitAuthExpired()
      }
      // 抛出业务错误，message 来自后端
      return Promise.reject(new Error(res.message || '操作失败'))
    }
    
    return res
  },
  error => {
    // HTTP 层面的错误（如 404、500、网络超时）
    console.error('请求错误:', error)
    
    // token过期：清除本地存储并通知UI弹出登录弹窗
    if (error.response?.status === 401) {
      emitAuthExpired()
    }
    
    // 优先使用后端返回的错误信息
    const message = error.response?.data?.message 
                 || error.message 
                 || '网络请求失败，请稍后重试'
    
    return Promise.reject(new Error(message))
  }
)

export default request
