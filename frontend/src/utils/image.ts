/**
 * 图片工具函数
 */

/**
 * 获取缩略图URL（WebP格式）
 * 将原图路径转换为缩略图路径：/uploads/covers/... → /uploads/thumbnails/covers/...webp
 * 如果缩略图不存在，前端通过 img @error 回退到原图
 * 
 * @param originalUrl 原图URL
 * @returns 缩略图URL，如果原图URL无效则返回空字符串
 */
export function getThumbUrl(originalUrl: string | undefined | null): string {
  if (!originalUrl) return ''
  
  // 只处理 /uploads/ 开头的本地图片
  if (!originalUrl.includes('/uploads/')) return originalUrl
  
  // 不处理已经是缩略图的路径
  if (originalUrl.includes('/thumbnails/')) return originalUrl
  
  // 构造缩略图路径：/uploads/xxx → /uploads/thumbnails/xxx.webp
  const thumbUrl = originalUrl
    .replace('/uploads/', '/uploads/thumbnails/')
    .replace(/\.[^.]+$/, '.webp')
  
  // 检查缩略图是否曾加载失败过，如果是则直接返回原图（避免重复请求不存在的缩略图）
  if (failedThumbs.has(thumbUrl)) return originalUrl
  
  return thumbUrl
}

/** 记录加载失败的缩略图路径，避免重复请求 */
const failedThumbs = new Set<string>()

/** 标记缩略图加载失败 */
export function markThumbFailed(thumbUrl: string) {
  failedThumbs.add(thumbUrl)
}

/**
 * 封面图加载失败时回退到原图
 * 用于 img 标签的 @error 事件
 * 
 * @param event 错误事件
 * @param originalUrl 原图URL
 */
export function onThumbError(event: Event, originalUrl: string | undefined | null) {
  const img = event.target as HTMLImageElement
  if (!img || !originalUrl) return
  
  // 避免原图也加载失败时无限循环
  const currentSrc = img.src
  if (!currentSrc.includes('/thumbnails/')) return
  
  img.src = originalUrl
}
