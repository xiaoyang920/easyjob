/**
 * 图片上传工具 - 支持进度回调
 */

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
export function uploadFile(options: UploadOptions): Promise<UploadResult> {
  const { url, file, onProgress } = options
  const formData = new FormData()
  formData.append('file', file)
  
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const token = localStorage.getItem('token')
    
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
        reject(new Error('登录已过期'))
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
