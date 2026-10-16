import axios from 'axios'
import { ensureAccessToken, recoverAccessToken, expireSession, waitForLogout } from './authSession'

type AuthConfig = import('axios').InternalAxiosRequestConfig & { _authRetried?: boolean; _authUser?: string | null }

async function retryAuth(config: AuthConfig) {
  if (config.url?.startsWith('/auth/')) throw new Error('登录信息不正确或已过期')
  const authorization = String(config.headers.Authorization || '')
  const rejected = authorization.startsWith('Bearer ') ? authorization.slice(7) : null
  if (config._authRetried) { expireSession(rejected); throw new Error('登录已过期，请重新登录') }
  const token = await recoverAccessToken(rejected, config._authUser ?? null)
  if (!token) throw new Error('登录状态已改变，请重新操作')
  config._authRetried = true
  config.headers.Authorization = `Bearer ${token}`
  return request(config)
}

const request = axios.create({
  // 无论是开发还是生产，统一使用 /api 前缀
  // 生产环境下，它会请求 http://你的服务器IP/api/... 并由 Nginx 转发到 8080
  baseURL: '/api', 
  timeout: 10000
})

// 请求拦截器 - 自动添加token
request.interceptors.request.use(
  async (config: AuthConfig) => {
    const authEndpoint = config.url?.startsWith('/auth/')
    const user = config._authUser !== undefined ? config._authUser : localStorage.getItem('userId')
    if (authEndpoint) await waitForLogout()
    const token = authEndpoint ? localStorage.getItem('token') : await ensureAccessToken()
    if (!authEndpoint && user !== localStorage.getItem('userId')) throw new Error('登录账号已改变，请重新操作')
    config._authUser = localStorage.getItem('userId')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    } else delete config.headers.Authorization
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
        return retryAuth(response.config)
      }
      // 抛出业务错误，message 来自后端
      return Promise.reject(Object.assign(new Error(res.message || '操作失败'), {code: res.code}))
    }
    
    return res
  },
  error => {
    if (axios.isCancel(error)) return Promise.reject(error)
    // HTTP 层面的错误（如 404、500、网络超时）
    console.error('请求失败:', error.response?.status || 'network')
    
    // token过期：清除本地存储并通知UI弹出登录弹窗
    if (error.response?.status === 401) {
      return retryAuth(error.config)
    }
    
    // 优先使用后端返回的错误信息
    const message = error.response?.data?.message 
                 || error.message 
                 || '网络请求失败，请稍后重试'
    
    const retrySeconds = Number(error.response?.headers?.['retry-after'])
    return Promise.reject(Object.assign(new Error(message), {
      code: error.response?.status || error.response?.data?.code,
      retryAfterMs: Number.isFinite(retrySeconds) && retrySeconds > 0 ? Math.min(300000, retrySeconds * 1000) : undefined
    }))
  }
)

export default request
