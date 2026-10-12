import { Marked, type Tokens } from 'marked'
// 带扩展名：AiChat 的单元测试直接用 Node 加载本文件，Node 的 ESM 解析不会补全 .ts
import hljs from './highlight.ts'

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/**
 * 对话回答专用的 Markdown 渲染器。
 * 代码块输出 highlight.js 标记，配色与文章页共用 styles/theme.css 中的墨色代码块。
 * 使用独立实例而不是全局 marked，避免高亮标记进入草稿编辑器的 HTML。
 */
const chatMarked = new Marked({
  breaks: true,
  gfm: true,
  renderer: {
    code({ text, lang }: Tokens.Code): string {
      const language = (lang || '').trim().split(/\s+/)[0].toLowerCase()
      const known = language !== '' && !!hljs.getLanguage(language)
      const body = known ? hljs.highlight(text, { language, ignoreIllegals: true }).value : escapeHtml(text)
      return `<pre><code class="hljs${known ? ` language-${language}` : ''}">${body}</code></pre>\n`
    },
  },
})

/** 渲染结果仍需经过 safeHtml 才能插入页面 */
export function renderChatMarkdown(markdown: string): string {
  return chatMarked.parse(markdown, { async: false })
}
