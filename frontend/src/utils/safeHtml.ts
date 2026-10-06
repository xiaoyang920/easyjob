import DOMPurify from 'dompurify'

// Apply at the display boundary too: older database rows and model HTML are untrusted.
export function safeHtml(html: string): string {
  return DOMPurify.sanitize(html || '', {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select'],
    FORBID_ATTR: ['style', 'srcset'],
    ALLOW_DATA_ATTR: false,
  })
}
