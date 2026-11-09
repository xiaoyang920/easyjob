import DOMPurify from 'dompurify'
import { articleTextStyle } from './articleTextStyle.ts'

// Retain bounded toolbar presentation while keeping arbitrary CSS forbidden.
DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
  if (data.attrName !== 'style') return
  const style = articleTextStyle(node.nodeName, data.attrValue)
  if (style) {
    node.setAttribute('style', style)
    data.forceKeepAttr = true
  }
})

// Apply at the display boundary too: older database rows and model HTML are untrusted.
export function safeHtml(html: string): string {
  return DOMPurify.sanitize(html || '', {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select'],
    FORBID_ATTR: ['style', 'srcset'],
    ALLOW_DATA_ATTR: false,
  })
}
