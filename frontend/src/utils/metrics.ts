export function formatDurationMs(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return ''
  return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(1)}s`
}

export function formatTokenCount(value?: number | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return ''
  return Math.round(value).toLocaleString('en-US')
}

export function formatRequestMetrics(metrics: {
  durationMs?: number | null
  inputTokens?: number | null
  outputTokens?: number | null
}): string {
  const parts: string[] = []
  const duration = formatDurationMs(metrics.durationMs)
  const input = formatTokenCount(metrics.inputTokens)
  const output = formatTokenCount(metrics.outputTokens)
  if (duration) parts.push(`总耗时 ${duration}`)
  if (input) parts.push(`输入 ${input} Token`)
  if (output) parts.push(`输出 ${output} Token`)
  return parts.join(' · ')
}
