import http from './http'
import type { UserProfile } from '@/types'

export const getProfile = () =>
  http.get<UserProfile>('/users/me/profile').then((r) => r.data)

/** partial update：只提交用户实际改动过的字段（后端按 exclude_unset 合并）。 */
export const updateProfile = (patch: Partial<UserProfile>) =>
  http.put<UserProfile>('/users/me/profile', patch).then((r) => r.data)
