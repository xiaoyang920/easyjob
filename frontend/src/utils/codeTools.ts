import hljs from './highlight'

export function codeLanguage(code: HTMLElement): string { return Array.from(code.classList).find(name => /^(language|lang)-/.test(name))?.replace(/^(language|lang)-/, '') || '' }
export function decorateCodeBlocks(root: HTMLElement, highlight = false) {
  root.querySelectorAll('pre:not(.streaming-table)').forEach((pre, index) => {
    let code = pre.querySelector('code')
    if (!code) { code = document.createElement('code'); code.textContent = pre.textContent; pre.replaceChildren(code) }
    if (highlight && !code.dataset.highlighted) hljs.highlightElement(code)
    if (pre.querySelector('.article-code-toolbar')) return
    const toolbar = document.createElement('div'), language = document.createElement('span'), expand = document.createElement('button')
    toolbar.className = 'article-code-toolbar'; language.textContent = codeLanguage(code) || '代码'
    expand.type = 'button'; expand.dataset.codeAction = 'expand'; expand.textContent = '放大查看'
    expand.setAttribute('aria-label', `放大第 ${index + 1} 个代码块`)
    toolbar.append(language, expand); pre.prepend(toolbar)
  })
}
export function clickedCode(event: MouseEvent, root?: HTMLElement) {
  const button = (event.target as HTMLElement).closest('button[data-code-action="expand"]')
  if (!button || !root?.contains(button)) return
  const code = button.closest('pre')?.querySelector('code')
  return code ? { text: code.textContent || '', language: codeLanguage(code) } : undefined
}
