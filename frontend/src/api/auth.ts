import http from './http'
import type { TokenResponse, UserMe } from '@/types'

export const register = (username: string, password: string) =>
  http.post<TokenResponse>('/auth/register', { username, password }).then((r) => r.data)

export const login = (username: string, password: string) =>
  http.post<TokenResponse>('/auth/login', { username, password }).then((r) => r.data)

export const me = () => http.get<UserMe>('/auth/me').then((r) => r.data)
