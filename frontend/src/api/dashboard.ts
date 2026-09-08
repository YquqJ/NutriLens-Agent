import http from './http'
import type { DailySummary, TrendSeries } from '@/types'

export const getSummary = (date?: string) =>
  http
    .get<DailySummary>('/dashboard/summary', { params: { date } })
    .then((r) => r.data)

export const getTrend = (days = 7) =>
  http.get<TrendSeries>('/dashboard/trend', { params: { days } }).then((r) => r.data)
