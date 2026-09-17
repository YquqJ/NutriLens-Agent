// 路由：登录页独立，业务页统一挂在 AppShell（侧栏布局）下。
// 未登录访问业务页 → 重定向登录页。

import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '@/api/http'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: () => import('@/components/AppShell.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'chat', name: 'chat', component: () => import('@/views/ChatView.vue') },
        { path: 'dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
        { path: 'records', name: 'records', component: () => import('@/views/RecordsView.vue') },
        { path: 'plan', name: 'plan', component: () => import('@/views/PlanView.vue') },
        { path: 'profile', name: 'profile', component: () => import('@/views/ProfileView.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !getToken()) return { path: '/login' }
  if (to.path === '/login' && getToken()) return { path: '/chat' }
  return true
})

export default router
