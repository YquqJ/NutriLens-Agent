// 从 axios 异常里提取后端返回的 detail（FastAPI HTTPException 结构），
// 兜底为通用文案，避免把网络错误原文直接甩给用户。

import { AxiosError } from 'axios'

export function getErrorMessage(e: unknown, fallback = '操作失败，请稍后重试'): string {
  if (e instanceof AxiosError) {
    const detail = e.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  }
  return fallback
}
