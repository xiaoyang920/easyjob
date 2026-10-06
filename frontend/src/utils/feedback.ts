import { ElMessage, ElMessageBox } from 'element-plus'

export const notify = {
  success: (message: string) => ElMessage({ message, type: 'success', grouping: true }),
  warning: (message: string) => ElMessage({ message, type: 'warning', grouping: true }),
  error: (message: string) => ElMessage({ message, type: 'error', grouping: true, duration: 4500 })
}
export function errorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof Error) || !error.message) return fallback
  if (/Network Error|Failed to fetch/i.test(error.message)) return '网络连接失败，请检查网络后重试'
  if (/timeout|timed out/i.test(error.message)) return '请求超时，请稍后重试'
  if (/Request failed with status code 5\d\d/i.test(error.message)) return '服务暂时不可用，请稍后重试'
  return error.message
}
export async function confirmAction(message: string, title: string, options: { confirmText?: string; type?: 'warning' | 'error' | 'info' } = {}): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, { confirmButtonText: options.confirmText || '确定', cancelButtonText: '取消',
      type: options.type || 'warning', customClass: 'ej-confirm', closeOnClickModal: false })
    return true
  } catch { return false }
}
