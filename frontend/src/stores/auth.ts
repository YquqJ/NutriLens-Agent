// 认证状态：token 持久化 + 当前用户名。刷新时用 /auth/me 校验 token 有效性。

import { defineStore } from 'pinia'
import { getToken, setToken, clearToken } from '@/api/http'
import * as authApi from '@/api/auth'
import type { UserMe } from '@/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    username: localStorage.getItem('nutrilens_username') ?? '',
    user: null as UserMe | null,
  }),
  getters: {
    isLoggedIn: () => !!getToken(),
  },
  actions: {
    async login(username: string, password: string) {
      const { token } = await authApi.login(username, password)
      setToken(token)
      this.username = username
      localStorage.setItem('nutrilens_username', username)
    },
    async register(username: string, password: string) {
      const { token } = await authApi.register(username, password)
      setToken(token)
      this.username = username
      localStorage.setItem('nutrilens_username', username)
    },
    /** 启动时校验 token：有效则回填用户信息，无效则清空。 */
    async bootstrap(): Promise<boolean> {
      if (!getToken()) return false
      try {
        this.user = await authApi.me()
        this.username = this.user.username
        return true
      } catch {
        clearToken()
        this.username = ''
        return false
      }
    },
    logout() {
      clearToken()
      this.username = ''
      this.user = null
      localStorage.removeItem('nutrilens_username')
    },
  },
})
