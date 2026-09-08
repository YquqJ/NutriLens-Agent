<script setup lang="ts">
// 身体档案页：编辑身体数据与目标，提交后后端重算 BMR/TDEE/热量目标并回显。
// 提交走 partial update —— 只发非空字段，未填的字段不覆盖已有值。
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getProfile, updateProfile } from '@/api/profile'
import { getErrorMessage } from '@/utils/error'
import type { UserProfile } from '@/types'

const loading = ref(false)
const saving = ref(false)
// 计算结果（后端回填，前端只读展示）
const result = reactive<{ bmr: number | null; tdee: number | null; calorie_target: number | null }>({
  bmr: null,
  tdee: null,
  calorie_target: null,
})

const form = reactive({
  gender: null as string | null,
  age: null as number | null,
  height_cm: null as number | null,
  weight_kg: null as number | null,
  activity_level: null as string | null,
  goal: null as string | null,
  goal_note: '',
})

const activityOptions = [
  { value: 'sedentary', label: '久坐（几乎不运动）' },
  { value: 'light', label: '轻度（每周 1–3 次）' },
  { value: 'moderate', label: '中度（每周 3–5 次）' },
  { value: 'active', label: '高度（每周 6–7 次）' },
]
const goalOptions = [
  { value: 'lose', label: '减脂' },
  { value: 'maintain', label: '维持' },
  { value: 'gain', label: '增重 / 增肌' },
]

function fill(p: UserProfile) {
  form.gender = p.gender
  form.age = p.age
  form.height_cm = p.height_cm
  form.weight_kg = p.weight_kg
  form.activity_level = p.activity_level
  form.goal = p.goal
  form.goal_note = p.goal_note
  result.bmr = p.bmr
  result.tdee = p.tdee
  result.calorie_target = p.calorie_target
}

async function load() {
  loading.value = true
  try {
    fill(await getProfile())
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    // partial update：过滤掉 null / 空串，避免覆盖未填字段
    const patch: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(form)) {
      if (v !== null && v !== undefined && v !== '') patch[k] = v
    }
    const updated = await updateProfile(patch as Partial<UserProfile>)
    fill(updated)
    ElMessage.success('档案已保存')
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>身体档案</h1>
      <p>填写身体数据与目标，系统据此计算你的每日热量目标。</p>
    </div>

    <div v-loading="loading" class="layout">
      <!-- 左：表单 -->
      <section class="panel form-card">
        <h2 class="card-title">基础数据</h2>
        <el-form label-position="top">
          <div class="row">
            <el-form-item label="性别">
              <el-radio-group v-model="form.gender">
                <el-radio-button value="male">男</el-radio-button>
                <el-radio-button value="female">女</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="年龄">
              <el-input-number v-model="form.age" :min="10" :max="100" controls-position="right" style="width: 100%" />
            </el-form-item>
          </div>

          <div class="row">
            <el-form-item label="身高（cm）">
              <el-input-number v-model="form.height_cm" :min="80" :max="250" :precision="0" controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item label="体重（kg）">
              <el-input-number v-model="form.weight_kg" :min="25" :max="300" :precision="1" controls-position="right" style="width: 100%" />
            </el-form-item>
          </div>

          <el-form-item label="活动水平">
            <el-select v-model="form.activity_level" placeholder="选择你的日常活动量" style="width: 100%">
              <el-option v-for="o in activityOptions" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
          </el-form-item>

          <el-form-item label="目标">
            <el-radio-group v-model="form.goal">
              <el-radio-button v-for="o in goalOptions" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="长期偏好 / 过敏（选填）">
            <el-input
              v-model="form.goal_note"
              type="textarea"
              :rows="3"
              placeholder="如：乳糖不耐、不吃猪肉、增肌期高蛋白……"
            />
          </el-form-item>

          <el-button type="primary" :loading="saving" @click="save">保存档案</el-button>
        </el-form>
      </section>

      <!-- 右：计算结果 -->
      <section class="panel result-card">
        <h2 class="card-title">能量测算</h2>
        <p class="hint">由你的身体数据自动计算，随档案更新。</p>

        <div class="metric">
          <div class="metric-label">基础代谢（BMR）</div>
          <div class="metric-value">
            <span class="num">{{ result.bmr != null ? Math.round(result.bmr) : '—' }}</span>
            <span class="unit">kcal/天</span>
          </div>
        </div>
        <div class="metric">
          <div class="metric-label">每日总消耗（TDEE）</div>
          <div class="metric-value">
            <span class="num">{{ result.tdee != null ? Math.round(result.tdee) : '—' }}</span>
            <span class="unit">kcal/天</span>
          </div>
        </div>
        <div class="metric target">
          <div class="metric-label">建议每日摄入</div>
          <div class="metric-value">
            <span class="num">{{ result.calorie_target != null ? Math.round(result.calorie_target) : '—' }}</span>
            <span class="unit">kcal/天</span>
          </div>
        </div>

        <div v-if="result.calorie_target == null" class="empty-note">
          完善左侧数据后，这里会给出你的热量目标。
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 20px;
  align-items: start;
}
.form-card,
.result-card {
  padding: 24px;
}
.card-title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
}
.hint {
  margin: 0 0 20px;
  color: var(--ink-3);
  font-size: 13px;
}
.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.metric {
  padding: 14px 0;
  border-top: 1px solid var(--line);
}
.metric-label {
  font-size: 13px;
  color: var(--ink-3);
}
.metric-value {
  margin-top: 4px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.metric-value .num {
  font-size: 26px;
}
.unit {
  margin-left: 6px;
  font-size: 13px;
  font-weight: 400;
  color: var(--ink-3);
}
.metric.target .metric-value {
  color: var(--primary-deep);
}
.empty-note {
  margin-top: 16px;
  padding: 12px;
  background: var(--bg);
  border-radius: var(--radius-sm);
  color: var(--ink-3);
  font-size: 13px;
}
</style>
