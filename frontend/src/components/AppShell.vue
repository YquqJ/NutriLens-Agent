<script setup lang="ts">
// 应用外壳：桌面端浅色侧栏，窄屏退化为顶部快捷导航。
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const nav = [
  { path: '/dashboard', label: '今日', icon: 'Odometer' },
  { path: '/records', label: '记录', icon: 'Notebook' },
  { path: '/chat', label: '对话', icon: 'ChatDotRound' },
  { path: '/plan', label: '计划', icon: 'Calendar' },
  { path: '/profile', label: '档案', icon: 'User' },
]

// 当前一级路径（/chat → chat），用于高亮激活项
const active = computed(() => '/' + (route.path.split('/')[1] ?? 'chat'))

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <aside class="side">
      <div class="brand">
        <span class="brand-mark">N</span>
        <span class="brand-name">NutriLens</span>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: active === item.path }"
        >
          <el-icon :size="17"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="side-foot">
        <div class="user">
          <span class="user-avatar">{{ (auth.username || '?').slice(0, 1).toUpperCase() }}</span>
          <span class="user-name">{{ auth.username || '未登录' }}</span>
        </div>
        <el-button text size="small" class="logout" @click="logout">
          <el-icon><SwitchButton /></el-icon>&nbsp;退出
        </el-button>
      </div>
    </aside>

    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<style scoped lang="scss">
.shell {
  display: flex;
  height: 100%;
  background: #eef5ef;
}
.side {
  width: 216px;
  flex: none;
  display: flex;
  flex-direction: column;
  background: var(--bg-elevated);
  border-right: 1px solid var(--line);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--line);
}
.brand-mark {
  width: 28px;
  height: 28px;
  flex: none;
  display: grid;
  place-items: center;
  background: var(--primary);
  color: #fff;
  font-weight: 700;
  font-size: 15px;
  border-radius: 7px;
}
.brand-name {
  font-weight: 600;
  font-size: 16px;
  letter-spacing: -0.01em;
}
.nav {
  flex: 1;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  color: var(--ink-2);
  font-weight: 500;
  transition:
    background 0.12s,
    color 0.12s;
}
.nav-item:hover {
  background: var(--bg);
  color: var(--ink);
}
.nav-item.active {
  background: var(--primary-soft);
  color: var(--primary-deep);
}
.side-foot {
  padding: 16px;
  border-top: 1px solid var(--line);
}
.user {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.user-avatar {
  width: 28px;
  height: 28px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--bg);
  border: 1px solid var(--line-strong);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
}
.user-name {
  font-weight: 500;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.logout {
  color: var(--ink-3);
}
.main {
  flex: 1;
  overflow-y: auto;
  margin: 16px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 12px;
}
.main > .page-wrapper {
  padding: 32px;
}

@media (max-width: 760px) {
  .shell {
    display: block;
  }
  .side {
    width: auto;
    height: auto;
    position: sticky;
    top: 0;
    z-index: 10;
    flex-direction: row;
    align-items: center;
    padding: 10px 12px;
  }
  .brand {
    padding: 0;
  }
  .brand-name,
  .side-foot {
    display: none;
  }
  .nav {
    flex: 1;
    flex-direction: row;
    justify-content: flex-end;
    padding: 0;
    overflow-x: auto;
  }
  .nav-item {
    flex: none;
    padding: 9px;
  }
  .nav-item span {
    display: none;
  }
  .main {
    overflow: visible;
    margin: 0;
    padding: 24px 16px 32px;
    border: 0;
    border-radius: 0;
  }
}
</style>
