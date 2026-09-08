// axios 单例：baseURL 走 /api（vite 代理到后端），JWT 注入 + 401 统一跳登录。

import axios from 'axios'

const TOKEN_KEY = 'nutrilens_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

const http = axios.create({ baseURL: '/api', timeout: 30000 })

http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    // token 失效 / 未登录：清凭证回登录页（避免死循环：登录接口自身 401 不跳）
    const url: string = error?.config?.url ?? ''
    if (error?.response?.status === 401 && !url.includes('/auth/')) {
      clearToken()
      if (location.pathname !== '/login') location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export default http
