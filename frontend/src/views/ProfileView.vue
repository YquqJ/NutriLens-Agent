<script setup lang="ts">
// 身体档案页：编辑身体数据与目标，提交后后端重算 BMR/TDEE/热量目标并回显。
// 提交走 partial update —— 只发非空字段，未填的字段不覆盖已有值。
// 交互：未填过资料直接进入编辑态；填过后默认只读，卡片右上角"编辑"切换出保存按钮。
// 只读态用 readonly（而非 disabled）保证文字不灰；select/radio 无 readonly 属性，
// 用 disabled 实现并覆盖样式回正常观感。
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getProfile, updateProfile } from '@/api/profile'
import { getErrorMessage } from '@/utils/error'
import type { UserProfile } from '@/types'

const loading = ref(false)
const saving = ref(false)
const filled = ref(false) // 是否已填过资料
const editing = ref(true) // 编辑态：未填过默认开启，填过后默认只读
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

const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')
const goalLabel = computed(() => {
  const g = goalOptions.find((o) => o.value === form.goal)
  return g ? `目标：${g.label}` : '目标：未设置'
})

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
    const p = await getProfile()
    fill(p)
    filled.value = !!(p.gender || p.age || p.height_cm || p.weight_kg || p.activity_level || p.goal)
    editing.value = !filled.value
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

function startEdit() {
  editing.value = true
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
    filled.value = true
    editing.value = false
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
  <div class="page-wrapper">
    <div class="page-head">
      <span class="page-kicker">个人健康档案</span>
      <h1>身体档案</h1>
      <p>填写身体数据与目标，系统据此计算你的每日热量目标。</p>
    </div>

    <div v-loading="loading" class="layout">
      <!-- 左：表单 -->
      <section class="panel form-card" :class="{ 'is-editing': editing }">
        <div class="card-head">
          <h2 class="card-title">基础数据</h2>
          <el-button v-if="filled && !editing" class="edit-btn" text @click="startEdit">
            <el-icon><EditPen /></el-icon>&nbsp;编辑
          </el-button>
        </div>

        <el-form class="profile-form" label-position="top">
          <el-form-item label="性别">
            <el-radio-group v-model="form.gender" :disabled="!editing">
              <el-radio-button value="male">男</el-radio-button>
              <el-radio-button value="female">女</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <div class="row-3">
            <el-form-item label="年龄">
              <el-input-number v-model="form.age" :min="10" :max="100" :readonly="!editing" controls-position="right" />
            </el-form-item>
            <el-form-item label="身高（cm）">
              <el-input-number v-model="form.height_cm" :min="80" :max="250" :precision="0" :readonly="!editing" controls-position="right" />
            </el-form-item>
            <el-form-item label="体重（kg）">
              <el-input-number v-model="form.weight_kg" :min="25" :max="300" :precision="1" :readonly="!editing" controls-position="right" />
            </el-form-item>
          </div>

          <el-form-item label="活动水平">
            <el-select
              v-model="form.activity_level"
              :disabled="!editing"
              placeholder="选择你的日常活动量"
              class="field-select"
            >
              <el-option v-for="o in activityOptions" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
          </el-form-item>

          <el-form-item label="目标">
            <el-radio-group v-model="form.goal" :disabled="!editing">
              <el-radio-button v-for="o in goalOptions" :key="o.value" :value="o.value">{{ o.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="长期偏好 / 过敏（选填）">
            <el-input
              v-model="form.goal_note"
              :readonly="!editing"
              type="textarea"
              :rows="3"
              placeholder="如：乳糖不耐、不吃猪肉、增肌期高蛋白……"
            />
          </el-form-item>

          <div v-if="editing">
            <el-button type="primary" :loading="saving" @click="save">保存档案</el-button>
            <el-button @click="editing = false">取消</el-button>
          </div>
        </el-form>
      </section>

      <!-- 右：计算结果 -->
      <section class="panel result-card">
        <h2 class="card-title">能量测算</h2>
        <p class="hint">由你的身体数据自动计算，随档案更新。</p>

        <div class="target-box">
          <div class="tb-label">建议每日摄入</div>
          <div class="tb-value">
            <span class="num">{{ result.calorie_target != null ? fmt(result.calorie_target) : '—' }}</span>
            <span class="tb-unit">千卡 / 天</span>
          </div>
          <div class="tb-note">{{ goalLabel }}</div>
        </div>

        <div class="split">
          <div class="mini">
            <div class="mini-label">基础代谢 BMR</div>
            <div class="mini-value num">{{ result.bmr != null ? fmt(result.bmr) : '—' }}</div>
            <div class="mini-unit">千卡 / 天</div>
          </div>
          <div class="mini">
            <div class="mini-label">总消耗 TDEE</div>
            <div class="mini-value num">{{ result.tdee != null ? fmt(result.tdee) : '—' }}</div>
            <div class="mini-unit">千卡 / 天</div>
          </div>
        </div>

        <div v-if="result.calorie_target == null" class="empty-note">
          完善左侧数据后，这里会给出你的每日热量目标。
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped lang="scss">
/* 两卡等高：默认 stretch，去除 top 对齐 */
.layout {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 20px;
  align-items: stretch;
}
.form-card,
.result-card {
  padding: 24px;
}
.result-card {
  display: flex;
  flex-direction: column;
  border-top: 3px solid var(--primary);
}

/* ---- 卡片头：标题 + 右上角编辑按钮 ---- */
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
}
.edit-btn {
  flex: none;
  color: var(--primary);
  font-weight: 500;
}
.edit-btn:hover {
  color: var(--primary-deep);
}

.hint {
  margin: 0 0 20px;
  color: var(--ink-3);
  font-size: 13px;
}

/* 表单限宽，避免输入框在宽卡片里被拉得过长 */
.profile-form {
  max-width: 520px;
}
.profile-form :deep(.el-form-item) {
  margin-bottom: 18px;
}
.profile-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 600;
}
.profile-form :deep(.el-input-number),
.profile-form :deep(.el-input-number .el-input__wrapper),
.field-select {
  width: 100%;
}

/* 年龄 / 身高 / 体重：一行三列，三等分短宽 */
.row-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

/* 活动水平下拉：收窄，不放满整行 */
.field-select {
  max-width: 340px;
}

/* ---- 只读态：让 disabled 组件（select/radio）回归正常观感，文字不灰 ---- */
.form-card :deep(.el-select__wrapper.is-disabled) {
  background: var(--bg-elevated);
  color: var(--ink);
  box-shadow: 0 0 0 1px var(--line) inset;
  cursor: default;
}
.form-card :deep(.el-select__wrapper.is-disabled .el-select__selected-item) {
  color: var(--ink-2);
}
.form-card :deep(.el-select__wrapper.is-disabled .el-select__caret) {
  display: none;
}
.form-card :deep(.el-radio-button__original-radio:disabled + .el-radio-button__inner) {
  color: var(--ink-2);
  background-color: var(--bg-elevated);
  cursor: default;
}
.form-card :deep(.el-radio-button__original-radio:disabled:checked + .el-radio-button__inner) {
  color: #fff;
  background-color: var(--primary);
  outline-color: var(--primary);
  box-shadow: -1px 0 0 0 var(--primary);
}

/* 只读态隐藏数字步进按钮，避免误导（readonly 不可点） */
.form-card:not(.is-editing) :deep(.el-input-number__increase),
.form-card:not(.is-editing) :deep(.el-input-number__decrease) {
  display: none;
}

/* ---- 测算结果 ---- */
.target-box {
  padding: 20px;
  border-radius: var(--radius-sm);
  background: var(--primary-soft);
  border: 1px solid var(--primary-line);
  margin-bottom: 16px;
}
.tb-label {
  font-size: 13px;
  color: var(--primary-deep);
}
.tb-value {
  margin-top: 4px;
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--primary-deep);
}
.tb-value .num {
  font-size: 38px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1;
}
.tb-unit {
  font-size: 13px;
  color: var(--primary-deep);
  opacity: 0.75;
}
.tb-note {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-3);
}

.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.mini {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface);
}
.mini-label {
  font-size: 12px;
  color: var(--ink-3);
}
.mini-value {
  margin-top: 4px;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.mini-unit {
  font-size: 12px;
  color: var(--ink-3);
}

.empty-note {
  margin-top: auto;
  padding-top: 16px;
  padding: 12px;
  background: var(--bg);
  border-radius: var(--radius-sm);
  color: var(--ink-3);
  font-size: 13px;
}

@media (max-width: 1023px) {
  .layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .row-3 {
    grid-template-columns: 1fr;
  }
  .field-select {
    max-width: 100%;
  }
}
</style>
