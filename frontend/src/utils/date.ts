// 本地时区的今天（YYYY-MM-DD）。
// 不能用 new Date().toISOString().slice(0, 10)：那是 UTC 日期，
// 在东八区 00:00–07:59 会错位成昨天，导致看板/记录默认选中错误日期。
export function todayISO(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
