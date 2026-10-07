import { describe, expect, it } from 'vitest'
import { formatDurationMs, formatRequestMetrics, formatTokenCount } from './metrics'

describe('metrics formatting', () => {
  it('formats request duration in milliseconds or seconds', () => {
    expect(formatDurationMs(420)).toBe('420ms')
    expect(formatDurationMs(1840)).toBe('1.8s')
  })

  it('formats token counts with locale separators and handles missing values', () => {
    expect(formatTokenCount(2344)).toBe('2,344')
    expect(formatTokenCount(null)).toBe('')
    expect(formatTokenCount(undefined)).toBe('')
  })

  it('formats the compact trace-header metrics and omits unavailable values', () => {
    expect(
      formatRequestMetrics({ durationMs: 1840, inputTokens: 2344, outputTokens: 386 }),
    ).toBe('总耗时 1.8s · 输入 2,344 Token · 输出 386 Token')
    expect(formatRequestMetrics({ durationMs: null, inputTokens: 120 })).toBe(
      '输入 120 Token',
    )
    expect(formatRequestMetrics({})).toBe('')
  })
})
