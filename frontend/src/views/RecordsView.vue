<script setup lang="ts">
// 记录管理页：按日期查看饮食 / 运动记录，支持编辑克数/时长与删除。
// 编辑走 PUT 端点（后端按比例重算营养值 / 消耗），删除走 DELETE。
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listDietRecords, deleteDietRecord, updateDietRecord,
  listExerciseRecords, deleteExerciseRecord, updateExerciseRecord,
} from '@/api/records'
import { getErrorMessage } from '@/utils/error'
import { todayISO } from '@/utils/date'
import { confidenceLabel, mealLabel } from '@/utils/labels'
import type { DietRecord, ExerciseRecord } from '@/types'

const date = ref(todayISO())
const tab = ref('diet')
const loading = ref(false)

const dietRecords = ref<DietRecord[]>([])
const exerciseRecords = ref<ExerciseRecord[]>([])

// 编辑态：同一时刻只编辑一条（草稿深拷贝，取消即丢弃）
const editingDiet = ref<number | null>(null)
const dietDraft = ref<DietRecord | null>(null)
const editingEx = ref<number | null>(null)
const exDraft = ref<number | null>(null)

const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')

// 餐次颜色（单一来源，映射到 CSS 变量 --mc 供颜色混合）
const MEAL_COLORS: Record<string, string> = {
  breakfast: '#16a34a',
  lunch: '#c8861f',
  dinner: '#3a6b8f',
  snack: '#8a8e88',
}
const mealColor = (m: string) => MEAL_COLORS[m] || '#8a8e88'

async function load() {
  loading.value = true
  try {
    const [d, e] = await Promise.all([
      listDietRecords(date.value),
      listExerciseRecords(date.value),
    ])
    dietRecords.value = d
    exerciseRecords.value = e
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    loading.value = false
  }
}

// ---- 饮食编辑 ----
function startEditDiet(r: DietRecord) {
  editingDiet.value = r.id
  dietDraft.value = JSON.parse(JSON.stringify(r))
}
function cancelEditDiet() {
  editingDiet.value = null
  dietDraft.value = null
}
async function saveDiet(r: DietRecord) {
  const draft = dietDraft.value
  if (!draft) return
  try {
    const updated = await updateDietRecord(
      r.id,
      draft.items.map((it) => ({ id: it.id, grams: it.grams })),
    )
    const idx = dietRecords.value.findIndex((x) => x.id === r.id)
    if (idx >= 0) dietRecords.value[idx] = updated
    editingDiet.value = null
    dietDraft.value = null
    ElMessage.success('已保存')
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}
async function removeDiet(r: DietRecord) {
  try {
    await ElMessageBox.confirm('删除这条饮食记录？', '删除', { type: 'warning' })
  } catch {
    return
  }
  await deleteDietRecord(r.id)
  dietRecords.value = dietRecords.value.filter((x) => x.id !== r.id)
}

// ---- 运动编辑 ----
function startEditEx(r: ExerciseRecord) {
  editingEx.value = r.id
  exDraft.value = r.duration_minutes
}
function cancelEditEx() {
  editingEx.value = null
  exDraft.value = null
}
async function saveEx(r: ExerciseRecord) {
  if (exDraft.value == null) return
  try {
    const updated = await updateExerciseRecord(r.id, exDraft.value)
    const idx = exerciseRecords.value.findIndex((x) => x.id === r.id)
    if (idx >= 0) exerciseRecords.value[idx] = updated
    editingEx.value = null
    exDraft.value = null
    ElMessage.success('已保存')
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}
async function removeEx(r: ExerciseRecord) {
  try {
    await ElMessageBox.confirm('删除这条运动记录？', '删除', { type: 'warning' })
  } catch {
    return
  }
  await deleteExerciseRecord(r.id)
  exerciseRecords.value = exerciseRecords.value.filter((x) => x.id !== r.id)
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h1>记录</h1>
        <p>按日期查看、编辑或删除饮食与运动记录。</p>
      </div>
      <div class="date-control">
        <span class="date-label">日期</span>
        <el-date-picker
          v-model="date"
          type="date"
          value-format="YYYY-MM-DD"
          :clearable="false"
          class="date-pick"
          @change="load"
        />
      </div>
    </div>

    <el-tabs v-model="tab">
      <!-- 饮食记录 -->
      <el-tab-pane label="饮食" name="diet">
        <div v-if="!dietRecords.length" class="empty-state">
          <el-icon class="es-icon"><Dish /></el-icon>
          <span class="es-title">当日暂无饮食记录</span>
          <span class="es-hint">去「对话」页说一句"我吃了什么"，记录会自动落到这里</span>
        </div>

        <div v-for="r in dietRecords" :key="r.id" class="panel rec">
          <div class="rec-head">
            <span class="meal" :style="{ '--mc': mealColor(r.meal_type) }">
              <i class="meal-dot" />{{ mealLabel(r.meal_type) }}
            </span>
            <span class="source">{{ r.source === 'agent' ? '对话录入' : '手动录入' }}</span>
            <span class="total num">{{ fmt(r.totals.calories) }} 千卡</span>
            <div class="ops">
              <template v-if="editingDiet === r.id">
                <el-button size="small" type="primary" @click="saveDiet(r)">保存</el-button>
                <el-button size="small" @click="cancelEditDiet">取消</el-button>
              </template>
              <template v-else>
                <el-button size="small" text @click="startEditDiet(r)">编辑</el-button>
                <el-button size="small" text type="danger" @click="removeDiet(r)">删除</el-button>
              </template>
            </div>
          </div>

          <table class="items">
            <thead>
              <tr>
                <th>食物</th>
                <th>克数</th>
                <th class="r">热量</th>
                <th class="r">蛋白</th>
                <th class="r">脂肪</th>
                <th class="r">碳水</th>
                <th>来源</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in (editingDiet === r.id ? dietDraft!.items : r.items)" :key="it.id">
                <td class="food">{{ it.food_name }}</td>
                <td class="grams">
                  <template v-if="editingDiet === r.id">
                    <el-input-number
                      v-model="it.grams"
                      :min="1" :max="3000" :precision="0" size="small"
                      controls-position="right" style="width: 96px"
                    />
                  </template>
                  <template v-else>{{ it.grams }}</template>
                </td>
                <td class="r num">{{ Math.round(it.calories) }}</td>
                <td class="r num">{{ it.protein }}</td>
                <td class="r num">{{ it.fat }}</td>
                <td class="r num">{{ it.carbs }}</td>
                <td>
                  <el-tag :type="it.confidence === 'llm_estimate' ? 'warning' : 'info'" size="small" effect="plain">
                    {{ confidenceLabel(it.confidence) }}
                  </el-tag>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </el-tab-pane>

      <!-- 运动记录 -->
      <el-tab-pane label="运动" name="exercise">
        <div v-if="!exerciseRecords.length" class="empty-state">
          <el-icon class="es-icon"><Bicycle /></el-icon>
          <span class="es-title">当日暂无运动记录</span>
          <span class="es-hint">去「对话」页说一句"我跑了 30 分钟"，记录会自动落到这里</span>
        </div>

        <div v-for="r in exerciseRecords" :key="r.id" class="panel rec ex">
          <span class="ex-icon"><el-icon><Bicycle /></el-icon></span>
          <span class="ex-name">{{ r.exercise_type }}</span>
          <template v-if="editingEx === r.id">
            <el-input-number
              v-model="exDraft" :min="1" :max="1440" :precision="0" size="small"
              controls-position="right" style="width: 100px"
            />
            <span class="unit">分钟</span>
          </template>
          <template v-else>
            <span class="ex-dur num">{{ r.duration_minutes }} 分钟</span>
          </template>
          <span class="ex-kcal num">{{ fmt(r.calories_burned) }} 千卡</span>
          <div class="ops">
            <template v-if="editingEx === r.id">
              <el-button size="small" type="primary" @click="saveEx(r)">保存</el-button>
              <el-button size="small" @click="cancelEditEx">取消</el-button>
            </template>
            <template v-else>
              <el-button size="small" text @click="startEditEx(r)">编辑</el-button>
              <el-button size="small" text type="danger" @click="removeEx(r)">删除</el-button>
            </template>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.date-control {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
}
.date-label {
  font-size: 13px;
  color: var(--ink-3);
}
.date-pick {
  width: 168px;
}
.date-pick :deep(.el-input__wrapper) {
  background: var(--bg-elevated);
  box-shadow: 0 0 0 1px var(--line-strong) inset;
}

.rec {
  padding: 16px 20px;
  margin-bottom: 14px;
}
.rec-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

/* 餐次 chip：颜色来自 --mc（脚本按 meal_type 映射），底/描边用 color-mix 淡出 */
.meal {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 3px 11px 3px 9px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  color: var(--mc);
  background: color-mix(in srgb, var(--mc) 10%, #fff);
  border: 1px solid color-mix(in srgb, var(--mc) 24%, #fff);
}
.meal-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--mc);
}

.source {
  font-size: 12px;
  color: var(--ink-3);
  padding: 1px 8px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
}
.total {
  margin-left: auto;
  font-weight: 650;
  font-size: 15px;
  color: var(--primary-deep);
}
.ops {
  display: flex;
  align-items: center;
  gap: 4px;
}

.items {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.items th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-3);
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
}
.items th.r,
.items td.r {
  text-align: right;
}
.items td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
}
.items tbody tr {
  transition: background 0.1s;
}
.items tbody tr:hover {
  background: var(--bg);
}
.items tr:last-child td {
  border-bottom: none;
}
.items .food {
  font-weight: 500;
  color: var(--ink);
}
.grams {
  white-space: nowrap;
}

/* ---- 运动记录 ---- */
.ex {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
}
.ex-icon {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  font-size: 17px;
  color: var(--viz-burned);
  background: color-mix(in srgb, var(--viz-burned) 12%, #fff);
}
.ex-name {
  font-weight: 600;
  font-size: 15px;
}
.ex-dur {
  color: var(--ink-2);
}
.ex-kcal {
  margin-left: auto;
  font-weight: 650;
  color: var(--primary-deep);
}
.unit {
  color: var(--ink-3);
  font-size: 13px;
}
.ex .ops {
  margin-left: 0;
}
</style>
