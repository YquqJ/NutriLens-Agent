<script setup lang="ts">
// 登录 / 注册页。左右分栏：左侧品牌说明，右侧表单。
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'
import {
  clearRememberedCredentials,
  getRememberedCredentials,
  saveRememberedCredentials,
} from '@/utils/rememberedCredentials'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'login' | 'register'>('login')
const loading = ref(false)
const rememberCredentials = ref(false)
const form = reactive({ username: '', password: '' })

const features = [
  '从一段对话开始，记下饮食与运动',
  '看懂每天的能量收支和营养构成',
  '让 AI 把饮食与训练安排成可执行的计划',
]

async function submit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请填写用户名与密码')
    return
  }
  loading.value = true
  try {
    if (mode.value === 'login') await auth.login(form.username, form.password)
    else await auth.register(form.username, form.password)
    if (mode.value === 'login' && rememberCredentials.value) {
      saveRememberedCredentials({ username: form.username, password: form.password })
    } else {
      clearRememberedCredentials()
    }
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  form.password = ''
  rememberCredentials.value = false
}

onMounted(() => {
  const remembered = getRememberedCredentials()
  if (!remembered) return
  form.username = remembered.username
  form.password = remembered.password
  rememberCredentials.value = true
})
</script>

<template>
  <div class="login">
    <div class="brand-panel">
      <div class="brand">
        <span class="brand-mark">N</span>
        <span class="brand-name">NutriLens</span>
      </div>
      <div class="tagline">把健康计划<br />变成每天做得到的事</div>
      <p class="brand-copy">NutriLens 帮你把日常记录、能量变化与 AI 建议收在同一个轻松的工作台里。</p>
      <ul class="features">
        <li v-for="f in features" :key="f">
          <span class="dot" />{{ f }}
        </li>
      </ul>
    </div>

    <div class="form-panel">
      <div class="form-box">
        <h1>{{ mode === 'login' ? '登录' : '注册' }}</h1>
        <p class="sub">
          {{ mode === 'login' ? '欢迎回来，继续你的健康记录' : '创建账号，开始记录' }}
        </p>

        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input
              v-model="form.username"
              placeholder="2–64 位字符"
              autocomplete="username"
              maxlength="64"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              placeholder="至少 6 位"
              autocomplete="current-password"
              maxlength="64"
              @keyup.enter="submit"
            />
          </el-form-item>

          <div v-if="mode === 'login'" class="remember-row">
            <el-checkbox v-model="rememberCredentials">记住账号和密码</el-checkbox>
            <span>仅在当前设备保存</span>
          </div>

          <el-button
            type="primary"
            class="submit"
            :loading="loading"
            @click="submit"
          >
            {{ mode === 'login' ? '登录' : '注册并登录' }}
          </el-button>
        </el-form>

        <div class="switch">
          已有账号？
          <el-button link type="primary" @click="switchMode">
            {{ mode === 'login' ? '去注册' : '去登录' }}
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login {
  display: flex;
  height: 100%;
  background: #effaf2;
}
.brand-panel {
  width: 44%;
  flex: none;
  background: #138a40;
  color: #eaf3ef;
  padding: 48px 56px;
  display: flex;
  flex-direction: column;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  background: #fff;
  color: var(--primary);
  font-weight: 700;
  font-size: 17px;
  border-radius: 8px;
}
.brand-name {
  font-size: 20px;
  font-weight: 600;
  color: #fff;
}
.tagline {
  margin-top: 82px;
  font-size: 32px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: -0.01em;
  color: #fff;
}
.brand-copy {
  max-width: 380px;
  margin: 18px 0 0;
  color: #d6f4df;
  font-size: 16px;
  line-height: 1.75;
}
.features {
  margin-top: 36px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.features li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  color: #cfe3db;
}
.dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: #4fb08f;
}

.form-panel {
  flex: 1;
  display: grid;
  place-items: center;
  padding: 48px;
  background: #effaf2;
}
.form-box {
  width: 100%;
  max-width: 470px;
  min-height: 490px;
  padding: 44px;
  border: 1px solid var(--primary-line);
  border-radius: 12px;
  background: var(--bg-elevated);
  box-shadow: 0 18px 42px rgba(21, 128, 61, .08);
}
.form-box h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 650;
}
.sub {
  margin: 8px 0 30px;
  color: var(--ink-3);
  font-size: 15px;
}
.form-box :deep(.el-form-item__label) { padding-bottom: 7px; font-size: 15px; font-weight: 650; }
.form-box :deep(.el-input__wrapper) { min-height: 44px; padding: 0 13px; }
.form-box :deep(.el-input__inner) { font-size: 15px; }
.remember-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -2px 0 18px; color: var(--ink-3); font-size: 13px; }
.remember-row :deep(.el-checkbox__label) { font-size: 14px; color: var(--ink-2); }
.submit {
  width: 100%;
  min-height: 44px;
  margin-top: 4px;
  font-size: 16px;
}
.switch {
  margin-top: 24px;
  font-size: 14px;
  color: var(--ink-3);
  text-align: center;
}
@media (max-width: 760px) {
  .login { min-height: 100%; display: block; }
  .brand-panel { width: auto; padding: 28px 24px; }
  .tagline { margin-top: 36px; font-size: 27px; }
  .brand-copy,.features { display: none; }
  .form-panel { padding: 24px 16px 36px; }
  .form-box { min-height: 0; padding: 30px 22px; }
}
</style>
