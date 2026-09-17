import http from './http'
import type { HealthPlan } from '@/types'

export const getCurrentPlan = () =>
  http.get<HealthPlan | null>('/plans/current').then((r) => r.data)

export const saveCurrentPlan = (payload: {
  content: string
  conversation_id?: string | null
  title?: string
}) => http.post<HealthPlan>('/plans/current', payload).then((r) => r.data)
