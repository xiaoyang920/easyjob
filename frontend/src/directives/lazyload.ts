import type { DirectiveBinding } from 'vue'
import { markThumbFailed } from '@/utils/image'

interface LazyLoadOptions {
  src: string
  fallback?: string  // 缩略图加载失败时回退的原图URL
  loading?: string
  error?: string
  rootMargin?: string
  threshold?: number
}

// 默认占位图
const DEFAULT_LOADING = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"%3E%3Crect width="400" height="300" fill="%23f0f0f0"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" fill="%23ccc" font-size="20"%3E加载中...%3C/text%3E%3C/svg%3E'
const DEFAULT_ERROR = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"%3E%3Crect width="400" height="300" fill="%23f5f5f5"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" fill="%23999" font-size="18"%3E加载失败%3C/text%3E%3C/svg%3E'

// 预加载队列
const preloadQueue = new Set<string>()
const loadedImages = new Set<string>()

// 预加载图片
function preloadImage(src: string): Promise<void> {
  if (loadedImages.has(src) || preloadQueue.has(src)) {
    return Promise.resolve()
  }

  preloadQueue.add(src)

  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      loadedImages.add(src)
      preloadQueue.delete(src)
      resolve()
    }
    img.onerror = () => {
      preloadQueue.delete(src)
      resolve()
    }
    img.src = src
  })
}

// 获取后续需要预加载的图片元素
function getNextImages(currentEl: HTMLElement, count: number): HTMLElement[] {
  const allLazyImages = Array.from(
    document.querySelectorAll<HTMLElement>('[data-lazy-src]')
  )
  const currentIndex = allLazyImages.indexOf(currentEl)
  
  if (currentIndex === -1) return []
  
  return allLazyImages.slice(currentIndex + 1, currentIndex + 1 + count)
}

// 加载图片
function loadImage(el: HTMLImageElement, binding: DirectiveBinding<LazyLoadOptions>) {
  const { src, loading } = binding.value
  
  // 设置加载中状态
  if (loading) {
    el.src = loading
  } else {
    el.src = DEFAULT_LOADING
  }

  // 预加载后续3-4张图片
  const nextImages = getNextImages(el, 4)
  nextImages.forEach((nextEl) => {
    const nextSrc = nextEl.getAttribute('data-lazy-src')
    if (nextSrc) {
      preloadImage(nextSrc)
    }
  })

  // 加载当前图片
  const img = new Image()
  img.onload = () => {
    el.src = src
    loadedImages.add(src)
    el.classList.add('lazy-loaded')
    el.removeAttribute('data-lazy-src')
  }
  img.onerror = () => {
    const { fallback, error } = binding.value
    // 缩略图加载失败且有原图回退地址时，尝试加载原图
    if (fallback && fallback !== src) {
      // 记录失败的缩略图，下次直接用原图
      markThumbFailed(src)
      const fallbackImg = new Image()
      fallbackImg.onload = () => {
        el.src = fallback
        loadedImages.add(fallback)
        el.classList.add('lazy-loaded')
        el.removeAttribute('data-lazy-src')
      }
      fallbackImg.onerror = () => {
        el.src = error || DEFAULT_ERROR
        el.classList.add('lazy-error')
      }
      fallbackImg.src = fallback
    } else {
      el.src = error || DEFAULT_ERROR
      el.classList.add('lazy-error')
    }
  }
  img.src = src
}

// 创建 IntersectionObserver
const createObserver = (el: HTMLImageElement, binding: DirectiveBinding<LazyLoadOptions>) => {
  const options = {
    // 提前加载：图片距离视口底部 400px 时开始加载
    rootMargin: binding.value.rootMargin || '0px 0px 400px 0px',
    threshold: binding.value.threshold || 0.01
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        loadImage(el, binding)
        observer.unobserve(el)
      }
    })
  }, options)

  observer.observe(el)
  
  // 保存 observer 以便后续清理
  ;(el as any)._lazyObserver = observer
}

// 懒加载指令
export const lazyload = {
  mounted(el: HTMLImageElement, binding: DirectiveBinding<LazyLoadOptions>) {
    // 检查是否支持 IntersectionObserver
    if (!('IntersectionObserver' in window)) {
      // 不支持则直接加载
      loadImage(el, binding)
      return
    }

    // 保存原始 src 到 data 属性
    el.setAttribute('data-lazy-src', binding.value.src)
    
    // 设置加载中占位图
    el.src = binding.value.loading || DEFAULT_LOADING
    
    // 添加懒加载类名
    el.classList.add('lazy-loading')
    
    // 创建观察器
    createObserver(el, binding)
  },

  updated(el: HTMLImageElement, binding: DirectiveBinding<LazyLoadOptions>) {
    // 如果 src 改变了，重新加载
    if (binding.value.src !== binding.oldValue?.src) {
      const observer = (el as any)._lazyObserver
      if (observer) {
        observer.unobserve(el)
      }
      
      el.setAttribute('data-lazy-src', binding.value.src)
      createObserver(el, binding)
    }
  },

  unmounted(el: HTMLImageElement) {
    // 清理观察器
    const observer = (el as any)._lazyObserver
    if (observer) {
      observer.unobserve(el)
      observer.disconnect()
      delete (el as any)._lazyObserver
    }
  }
}

// 默认导出
export default lazyload
