/**
 * 图片上传工具 - 支持进度回调
 */

import { ensureAccessToken, recoverAccessToken, expireSession } from './authSession'

export interface UploadOptions {
  url: string
  file: File
  onProgress?: (percent: number) => void
}

export interface UploadResult {
  code: number
  message: string
  data?: {
    url: string
    fileName?: string
    path?: string
    thumbUrl?: string
  }
}

/**
 * 上传文件（带进度）
 */
export async function uploadFile(options: UploadOptions): Promise<UploadResult> {
  const user = localStorage.getItem('userId')
  let token = await ensureAccessToken()
  let retried = false
  const send = (): Promise<UploadResult> => {
    if (localStorage.getItem('userId') !== user) return Promise.reject(new Error('登录账号已改变，请重新上传'))
    const { url, file, onProgress } = options
    const formData = new FormData()
    formData.append('file', file)

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          const percent = Math.round((event.loaded / event.total) * 100)
          onProgress(percent)
        }
      }

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            reject(new Error('响应解析失败'))
          }
        } else if (xhr.status === 401) {
          if (retried) { expireSession(token); reject(new Error('登录已过期')); return }
          retried = true
          void recoverAccessToken(token, user).then(value => {
            if (!value) throw new Error('登录状态已改变，请重新上传')
            token = value
            return send()
          }).then(resolve, reject)
        } else {
          reject(new Error(`上传失败: ${xhr.status}`))
        }
      }

      xhr.onerror = () => reject(new Error('网络错误'))
      xhr.ontimeout = () => reject(new Error('上传超时'))

      xhr.open('POST', '/api' + url)
      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      }
      xhr.timeout = 60000
      xhr.send(formData)
    })
  }
  return send()
}
