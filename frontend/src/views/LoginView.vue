<script setup lang="ts">
// 登录 / 注册页。左右分栏：左侧品牌说明，右侧表单。
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/utils/error'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'login' | 'register'>('login')
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const features = [
  '拍照识别饮食，自动换算热量与宏量',
  '记录运动消耗，看板呈现每日收支',
  '基于知识库的营养与运动问答',
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
    router.push('/chat')
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  form.password = ''
}
</script>

<template>
  <div class="login">
    <div class="brand-panel">
      <div class="brand">
        <span class="brand-mark">N</span>
        <span class="brand-name">NutriLens</span>
      </div>
      <div class="tagline">记录饮食与运动<br />让每一口、每一步都算数</div>
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
}
.brand-panel {
  width: 44%;
  flex: none;
  background: var(--primary-deep);
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
  color: var(--primary-deep);
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
  margin-top: 72px;
  font-size: 26px;
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: -0.01em;
  color: #fff;
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
  font-size: 14px;
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
  padding: 40px;
}
.form-box {
  width: 100%;
  max-width: 360px;
}
.form-box h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
}
.sub {
  margin: 6px 0 24px;
  color: var(--ink-3);
  font-size: 13px;
}
.submit {
  width: 100%;
  margin-top: 4px;
}
.switch {
  margin-top: 20px;
  font-size: 13px;
  color: var(--ink-3);
  text-align: center;
}
</style>
