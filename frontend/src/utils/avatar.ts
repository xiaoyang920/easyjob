/**
 * 用户头像：有上传头像时使用原图，没有或加载失败时显示“昵称首字 + 主题色”的占位头像。
 * 占位头像是内联 SVG（data URI），随 img 尺寸缩放，沿用各页面现有的头像样式，无需额外请求。
 */

// 与文章卡片同一组纸色，文字统一用墨色，保证对比度
const PAPER_COLORS = ['#f3a093', '#b4a7ff', '#d3f795', '#e5dfff', '#e6e0d4']
const INK = '#11110f'
const FONT = "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif"

const placeholderCache = new Map<string, string>()

/** 昵称里第一个文字或数字（跳过空白、标点和表情），拉丁字母转大写；没有时返回空字符串 */
export function nameInitial(name?: string | null): string {
  const match = (name || '').trim().match(/[\p{L}\p{N}]/u)
  return match ? match[0].toUpperCase() : ''
}

function colorFor(name: string): string {
  let hash = 0
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) >>> 0
  return PAPER_COLORS[hash % PAPER_COLORS.length]
}

function escapeXml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** 同一个昵称总是得到同一种颜色；没有昵称时画一个墨色人像轮廓 */
export function avatarPlaceholder(name?: string | null): string {
  const key = (name || '').trim()
  const cached = placeholderCache.get(key)
  if (cached) return cached

  const initial = nameInitial(key)
  const glyph = initial
    ? `<text x="50" y="50" dominant-baseline="central" text-anchor="middle" font-family="${FONT}" font-size="44" font-weight="700" fill="${INK}">${escapeXml(initial)}</text>`
    : `<circle cx="50" cy="40" r="15" fill="${INK}"/><path d="M22 82c4-15 15-23 28-23s24 8 28 23z" fill="${INK}"/>`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="${colorFor(key)}"/>${glyph}</svg>`
  const uri = `data:image/svg+xml,${encodeURIComponent(svg)}`
  placeholderCache.set(key, uri)
  return uri
}

/** 头像地址：空值返回占位头像；后端拼出的 localhost:8080 绝对地址改为站内相对路径，交给开发代理或 Nginx */
export function avatarUrl(path?: string | null, name?: string | null): string {
  if (!path) return avatarPlaceholder(name)
  return path.replace(/^https?:\/\/(?:localhost|127\.0\.0\.1):8080(?=\/)/, '')
}

/** img 的 error 处理：换成占位头像；占位头像本身是内联 SVG，不会再次触发 error */
export function onAvatarError(event: Event, name?: string | null): void {
  const image = event.target as HTMLImageElement
  if (image.src.startsWith('data:')) return
  image.src = avatarPlaceholder(name)
}
