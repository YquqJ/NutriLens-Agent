<script setup lang="ts">
// 月历记录页：月度概览来自既有 dashboard summary，选中日沿用饮食/运动记录 CRUD。
import { computed, onMounted, ref } from 'vue'
import { Bicycle, Calendar, Dish, Lightning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSummary } from '@/api/dashboard'
import {
  deleteDietRecord,
  deleteExerciseRecord,
  listDietRecords,
  listExerciseRecords,
  updateDietRecord,
  updateExerciseRecord,
} from '@/api/records'
import type { DailySummary, DietRecord, ExerciseRecord } from '@/types'
import { buildMonthGrid, deriveCalendarDayState, type CalendarDayState } from '@/utils/calendar'
import { todayISO } from '@/utils/date'
import { getErrorMessage } from '@/utils/error'
import { confidenceLabel, mealLabel } from '@/utils/labels'

const date = ref(todayISO())
const month = ref(date.value.slice(0, 7))
const tab = ref('diet')
const loading = ref(false)
const monthLoading = ref(false)
const monthWarning = ref('')
const dietRecords = ref<DietRecord[]>([])
const exerciseRecords = ref<ExerciseRecord[]>([])
const summary = ref<DailySummary | null>(null)
const monthStates = ref<Record<string, CalendarDayState>>({})
const editingDiet = ref<number | null>(null)
const dietDraft = ref<DietRecord | null>(null)
const editingEx = ref<number | null>(null)
const exDraft = ref<number | null>(null)

const fmt = (value: number) => Math.round(value).toLocaleString('zh-CN')
const selectedState = computed(() => monthStates.value[date.value] ?? null)
const calendarDates = computed(() => {
  const [year, value] = month.value.split('-').map(Number)
  return buildMonthGrid(year, value)
})
const selectedDateText = computed(() => {
  const [year, value, day] = date.value.split('-')
  return `${year}年${Number(value)}月${Number(day)}日`
})

const MEAL_COLORS: Record<string, string> = {
  breakfast: '#16a34a',
  lunch: '#d69342',
  dinner: '#4d8ccb',
  snack: '#76857b',
}
const mealColor = (mealType: string) => MEAL_COLORS[mealType] || '#76857b'

function currentMonthDays() {
  return calendarDates.value.filter((value) => value.startsWith(month.value))
}

async function loadSelected() {
  loading.value = true
  try {
    const [nextDiet, nextExercise, nextSummary] = await Promise.all([
      listDietRecords(date.value),
      listExerciseRecords(date.value),
      getSummary(date.value),
    ])
    dietRecords.value = nextDiet
    exerciseRecords.value = nextExercise
    summary.value = nextSummary
    monthStates.value[date.value] = deriveCalendarDayState(date.value, nextSummary, nextDiet, nextExercise)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadMonth() {
  monthLoading.value = true
  monthWarning.value = ''
  const dates = currentMonthDays()
  const results = await Promise.allSettled(dates.map((value) => getSummary(value)))
  const nextStates: Record<string, CalendarDayState> = {}
  let failures = 0

  results.forEach((result, index) => {
    const value = dates[index]
    if (result.status === 'rejected') {
      failures += 1
      nextStates[value] = deriveCalendarDayState(value, null, [], [])
      return
    }
    const daily = result.value
    // 当前 API 没有月度 records 聚合；有摄入/消耗即可准确呈现绝大多数食/动状态。
    const diet = daily.intake > 0 ? ([{}] as DietRecord[]) : []
    const exercise = daily.burned > 0 ? ([{}] as ExerciseRecord[]) : []
    nextStates[value] = deriveCalendarDayState(value, daily, diet, exercise)
  })

  monthStates.value = nextStates
  if (failures > 0) monthWarning.value = `有 ${failures} 天的汇总暂时无法读取`
  monthLoading.value = false
}

async function changeMonth() {
  const selectedInMonth = date.value.startsWith(month.value)
  if (!selectedInMonth) date.value = `${month.value}-01`
  await Promise.all([loadMonth(), loadSelected()])
}

async function selectDate(value: string) {
  date.value = value
  if (!value.startsWith(month.value)) month.value = value.slice(0, 7)
  await loadSelected()
}

function startEditDiet(record: DietRecord) {
  editingDiet.value = record.id
  dietDraft.value = JSON.parse(JSON.stringify(record))
}
function cancelEditDiet() {
  editingDiet.value = null
  dietDraft.value = null
}
async function saveDiet(record: DietRecord) {
  if (!dietDraft.value) return
  try {
    const updated = await updateDietRecord(record.id, dietDraft.value.items.map((item) => ({ id: item.id, grams: item.grams })))
    const index = dietRecords.value.findIndex((item) => item.id === record.id)
    if (index >= 0) dietRecords.value[index] = updated
    cancelEditDiet()
    await Promise.all([loadSelected(), loadMonth()])
    ElMessage.success('饮食记录已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}
async function removeDiet(record: DietRecord) {
  try {
    await ElMessageBox.confirm('删除这条饮食记录？', '删除记录', { type: 'warning' })
    await deleteDietRecord(record.id)
    await Promise.all([loadSelected(), loadMonth()])
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(getErrorMessage(error))
  }
}

function startEditEx(record: ExerciseRecord) {
  editingEx.value = record.id
  exDraft.value = record.duration_minutes
}
function cancelEditEx() {
  editingEx.value = null
  exDraft.value = null
}
async function saveEx(record: ExerciseRecord) {
  if (exDraft.value == null) return
  try {
    const updated = await updateExerciseRecord(record.id, exDraft.value)
    const index = exerciseRecords.value.findIndex((item) => item.id === record.id)
    if (index >= 0) exerciseRecords.value[index] = updated
    cancelEditEx()
    await Promise.all([loadSelected(), loadMonth()])
    ElMessage.success('运动记录已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}
async function removeEx(record: ExerciseRecord) {
  try {
    await ElMessageBox.confirm('删除这条运动记录？', '删除记录', { type: 'warning' })
    await deleteExerciseRecord(record.id)
    await Promise.all([loadSelected(), loadMonth()])
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(getErrorMessage(error))
  }
}

onMounted(() => void Promise.all([loadMonth(), loadSelected()]))
</script>

<template>
  <div class="records-page">
    <header class="page-head records-head">
      <div>
        <span class="eyebrow">Records / Calendar</span>
        <h1>你的健康节奏，有迹可循</h1>
        <p>红点代表热量超标，薄荷绿代表目标内；食和动分别表示饮食与运动记录。</p>
      </div>
      <el-date-picker v-model="month" type="month" value-format="YYYY-MM" :clearable="false" class="month-picker" @change="changeMonth" />
    </header>

    <section v-loading="monthLoading" class="calendar-layout">
      <article class="calendar-panel panel">
        <div class="calendar-title"><div><h2>{{ month.replace('-', ' 年 ') }} 月</h2><p v-if="monthWarning">{{ monthWarning }}</p></div><el-icon><Calendar /></el-icon></div>
        <div class="week-row"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
        <div class="calendar-grid">
          <button v-for="value in calendarDates" :key="value" class="day-cell" :class="{ muted: !value.startsWith(month), selected: value === date }" @click="selectDate(value)">
            <span class="day-number"><b>{{ Number(value.slice(-2)) }}</b><i :class="['status-dot', monthStates[value]?.status ?? 'no_records']" /></span>
            <span class="flags"><i v-if="monthStates[value]?.hasDiet" class="record-flag diet">食</i><i v-if="monthStates[value]?.hasExercise" class="record-flag exercise">动</i></span>
            <small v-if="monthStates[value]?.hasDiet" class="day-intake num">{{ fmt(monthStates[value].intake) }} kcal</small>
            <small v-else-if="value.startsWith(month)" class="day-intake empty">无记录</small>
          </button>
        </div>
        <div class="calendar-legend"><span><i class="status-dot over_target" />热量超标</span><span><i class="status-dot within_target" />目标内</span><span><i class="record-flag diet">食</i>饮食</span><span><i class="record-flag exercise">动</i>运动</span></div>
      </article>

      <aside class="day-summary">
        <span class="eyebrow">Selected day</span>
        <h2>{{ selectedDateText }}</h2>
        <strong class="num">{{ fmt(summary?.intake ?? 0) }}</strong><span class="summary-unit">千卡摄入</span>
        <p class="summary-status" :class="selectedState?.status">{{ selectedState?.status === 'over_target' ? '今日摄入超过热量目标' : selectedState?.status === 'no_records' ? '当天还没有记录' : '当前摄入处于目标范围内' }}</p>
        <dl><div><dt>饮食记录</dt><dd>{{ dietRecords.length }} 条</dd></div><div><dt>运动记录</dt><dd>{{ exerciseRecords.length }} 条</dd></div><div><dt>运动消耗</dt><dd class="num">{{ fmt(summary?.burned ?? 0) }} kcal</dd></div></dl>
      </aside>
    </section>

    <section v-loading="loading" class="record-detail">
      <div class="detail-head"><div><h2>当天记录</h2><p>{{ selectedDateText }} 的饮食与运动明细</p></div><el-tabs v-model="tab"><el-tab-pane label="饮食" name="diet" /><el-tab-pane label="运动" name="exercise" /></el-tabs></div>

      <template v-if="tab === 'diet'">
        <div v-if="!dietRecords.length" class="empty-state panel"><el-icon class="es-icon"><Dish /></el-icon><span class="es-title">当日暂无饮食记录</span><span class="es-hint">去智能对话中描述你吃了什么，记录会自动落到这里。</span></div>
        <article v-for="record in dietRecords" :key="record.id" class="record-card panel">
          <header><span class="meal" :style="{ '--meal-color': mealColor(record.meal_type) }"><i />{{ mealLabel(record.meal_type) }}</span><span class="source">{{ record.source === 'agent' ? '对话录入' : '手动录入' }}</span><strong class="num">{{ fmt(record.totals.calories) }} 千卡</strong><div class="record-actions"><template v-if="editingDiet === record.id"><el-button size="small" type="primary" @click="saveDiet(record)">保存</el-button><el-button size="small" @click="cancelEditDiet">取消</el-button></template><template v-else><el-button size="small" text @click="startEditDiet(record)">编辑</el-button><el-button size="small" text type="danger" @click="removeDiet(record)">删除</el-button></template></div></header>
          <div class="item-list"><div v-for="item in (editingDiet === record.id ? dietDraft!.items : record.items)" :key="item.id" class="food-item"><div><b>{{ item.food_name }}</b><span>{{ confidenceLabel(item.confidence) }}</span></div><div class="food-values"><template v-if="editingDiet === record.id"><el-input-number v-model="item.grams" :min="1" :max="3000" :precision="0" size="small" controls-position="right" /></template><template v-else><b class="num">{{ item.grams }}g</b></template><span class="num">{{ Math.round(item.calories) }} kcal</span><span>蛋白 {{ item.protein }}g</span></div></div></div>
        </article>
      </template>

      <template v-else>
        <div v-if="!exerciseRecords.length" class="empty-state panel"><el-icon class="es-icon"><Bicycle /></el-icon><span class="es-title">当日暂无运动记录</span><span class="es-hint">去智能对话中说明运动类型和时长，记录会自动落到这里。</span></div>
        <article v-for="record in exerciseRecords" :key="record.id" class="exercise-card panel"><span class="exercise-icon"><el-icon><Lightning /></el-icon></span><div><b>{{ record.exercise_type }}</b><small>MET {{ record.met }}</small></div><template v-if="editingEx === record.id"><el-input-number v-model="exDraft" :min="1" :max="1440" :precision="0" size="small" controls-position="right" /><span>分钟</span></template><template v-else><span class="num">{{ record.duration_minutes }} 分钟</span></template><strong class="num">{{ fmt(record.calories_burned) }} 千卡</strong><div class="record-actions"><template v-if="editingEx === record.id"><el-button size="small" type="primary" @click="saveEx(record)">保存</el-button><el-button size="small" @click="cancelEditEx">取消</el-button></template><template v-else><el-button size="small" text @click="startEditEx(record)">编辑</el-button><el-button size="small" text type="danger" @click="removeEx(record)">删除</el-button></template></div></article>
      </template>
    </section>
  </div>
</template>

<style scoped>
.records-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }.eyebrow { display: block; margin-bottom: 6px; color: var(--primary-deep); font-size: 10px; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }.records-head h1 { font-size: 29px; }.month-picker { width: 154px; flex: none; }
.calendar-layout { display: grid; grid-template-columns: minmax(0,1fr) 310px; gap: 18px; margin-top: 26px; }.calendar-panel { padding: 20px; }.calendar-title { display: flex; align-items: flex-start; justify-content: space-between; }.calendar-title h2,.day-summary h2,.detail-head h2 { margin: 0; font-size: 17px; }.calendar-title p { margin: 4px 0 0; color: var(--warn); font-size: 11px; }.calendar-title .el-icon { color: var(--primary-deep); font-size: 20px; }.week-row,.calendar-grid { display: grid; grid-template-columns: repeat(7,1fr); gap: 6px; }.week-row { margin: 18px 0 7px; }.week-row span { color: var(--ink-3); text-align: center; font-size: 10px; }.day-cell { min-height: 78px; padding: 7px; border: 1px solid #e5ece7; border-radius: 7px; background: #fff; text-align: left; transition: transform .16s,border-color .16s; }.day-cell:hover { transform: translateY(-2px); border-color: var(--primary-line); }.day-cell.selected { padding: 6px; border: 2px solid var(--primary); background: var(--primary-soft); }.day-cell.muted { opacity: .38; }.day-number { display: flex; justify-content: space-between; align-items: center; }.day-number b { font-size: 11px; }.status-dot { width: 7px; height: 7px; display: inline-block; border-radius: 50%; background: #d7e1da; }.status-dot.within_target { background: var(--primary); }.status-dot.over_target { background: var(--warn); }.status-dot.no_target { background: var(--info); }.flags { display: flex; gap: 3px; min-height: 17px; margin-top: 7px; }.record-flag { width: 18px; height: 16px; display: inline-grid; place-items: center; border-radius: 3px; background: var(--primary-soft); color: var(--primary-deep); font-size: 8px; font-style: normal; font-weight: 800; }.record-flag.exercise { background: #eef6ff; color: var(--info); }.day-intake { display: block; overflow: hidden; margin-top: 4px; color: var(--ink-3); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }.day-intake.empty { color: #a3afa7; }.calendar-legend { display: flex; flex-wrap: wrap; gap: 11px; margin-top: 16px; color: var(--ink-3); font-size: 10px; }.calendar-legend span { display: inline-flex; align-items: center; gap: 4px; }
.day-summary { padding: 21px; border-radius: var(--radius); background: var(--primary); color: #fff; }.day-summary .eyebrow { color: #d5f8df; }.day-summary h2 { margin-top: 9px; }.day-summary > strong { display: inline-block; margin-top: 20px; font-size: 34px; line-height: 1; }.summary-unit { margin-left: 5px; color: #d5f8df; font-size: 11px; }.summary-status { display: inline-block; margin: 10px 0 0; padding: 5px 7px; border-radius: 4px; background: rgba(255,255,255,.13); color: #e7faed; font-size: 10px; }.summary-status.over_target { background: rgba(221,111,91,.28); }.day-summary dl { margin: 22px 0 0; }.day-summary dl div { display: flex; justify-content: space-between; padding: 10px 0; border-top: 1px solid rgba(255,255,255,.16); font-size: 11px; }.day-summary dt { color: #c7eed3; }.day-summary dd { margin: 0; font-weight: 700; }
.record-detail { margin-top: 22px; }.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }.detail-head p { margin: 4px 0 0; color: var(--ink-3); font-size: 12px; }.detail-head :deep(.el-tabs__header) { margin: 0; }.record-card { padding: 17px; margin-top: 12px; }.record-card header { display: flex; align-items: center; gap: 9px; }.meal { display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 5px; background: color-mix(in srgb, var(--meal-color) 10%, #fff); color: var(--meal-color); font-size: 11px; font-weight: 750; }.meal i { width: 6px; height: 6px; border-radius: 50%; background: var(--meal-color); }.source { padding: 3px 6px; border: 1px solid var(--line); border-radius: 4px; color: var(--ink-3); font-size: 10px; }.record-card header > strong { margin-left: auto; color: var(--primary-deep); font-size: 13px; }.record-actions { display: flex; gap: 2px; }.item-list { display: grid; gap: 0; margin-top: 13px; border-top: 1px solid var(--line); }.food-item { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 10px 0; border-bottom: 1px solid var(--line); }.food-item:last-child { border-bottom: 0; }.food-item b,.food-item span { display: block; }.food-item b { font-size: 12px; }.food-item > div:first-child span { margin-top: 2px; color: var(--ink-3); font-size: 10px; }.food-values { display: flex; align-items: center; gap: 14px; color: var(--ink-3); font-size: 11px; }.food-values b { color: var(--ink); }.exercise-card { display: flex; align-items: center; gap: 12px; padding: 17px; margin-top: 12px; }.exercise-icon { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 7px; background: #eef6ff; color: var(--info); }.exercise-card b,.exercise-card small { display: block; }.exercise-card b { font-size: 13px; }.exercise-card small { margin-top: 2px; color: var(--ink-3); font-size: 10px; }.exercise-card > strong { margin-left: auto; color: var(--primary-deep); }.empty-state { margin-top: 12px; }
@media (max-width: 1000px) { .calendar-layout { grid-template-columns: 1fr; }.day-summary { min-height: 200px; }.record-detail { margin-top: 18px; } }
@media (max-width: 680px) { .records-head { display: block; }.month-picker { margin-top: 14px; }.calendar-panel { padding: 13px; }.week-row,.calendar-grid { gap: 4px; }.day-cell { min-height: 65px; padding: 5px; }.day-cell.selected { padding: 4px; }.day-intake { font-size: 7px; }.detail-head { display: block; }.detail-head :deep(.el-tabs__header) { margin-top: 12px; }.record-card header { align-items: flex-start; flex-wrap: wrap; }.record-card header > strong { margin-left: 0; }.record-actions { margin-left: auto; }.food-item { align-items: flex-start; flex-direction: column; gap: 7px; }.food-values { width: 100%; justify-content: space-between; gap: 8px; }.exercise-card { flex-wrap: wrap; }.exercise-card > strong { margin-left: 0; }.exercise-card .record-actions { margin-left: auto; } }
</style>
