<script setup lang="ts">
// 月历记录页：月度概览来自既有 dashboard summary，选中日沿用饮食/运动记录 CRUD。
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, ArrowRight, Bicycle, Dish, Lightning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMonthlySummary, getSummary } from '@/api/dashboard'
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
const monthlySummaries = ref<Record<string, DailySummary>>({})
const editingDiet = ref<number | null>(null)
const dietDraft = ref<DietRecord | null>(null)
const editingEx = ref<number | null>(null)
const exDraft = ref<number | null>(null)

const fmt = (value: number) => Math.round(value).toLocaleString('zh-CN')
const today = todayISO()
const currentMonth = today.slice(0, 7)
const selectedState = computed(() => monthStates.value[date.value] ?? null)
const canMoveForward = computed(() => month.value < currentMonth)
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

function monthLabel(value: string) {
  const [year, monthValue] = value.split('-')
  return `${year} 年 ${Number(monthValue)} 月`
}

function isFutureDate(value: string) {
  return value > today
}

async function loadSelected() {
  loading.value = true
  try {
    const [nextDiet, nextExercise] = await Promise.all([
      listDietRecords(date.value),
      listExerciseRecords(date.value),
    ])
    const nextSummary = monthlySummaries.value[date.value] ?? await getSummary(date.value)
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
  const nextStates: Record<string, CalendarDayState> = {}
  try {
    const result = await getMonthlySummary(month.value)
    const summaries: Record<string, DailySummary> = {}
    result.days.forEach((daily) => {
      summaries[daily.date] = daily
      nextStates[daily.date] = deriveCalendarDayState(
        daily.date,
        daily,
        daily.has_diet ? ([{}] as DietRecord[]) : [],
        daily.has_exercise ? ([{}] as ExerciseRecord[]) : [],
      )
    })
    monthlySummaries.value = { ...monthlySummaries.value, ...summaries }
    monthStates.value = nextStates
  } catch (error) {
    monthWarning.value = getErrorMessage(error, '月份汇总暂时无法读取')
  } finally {
    monthLoading.value = false
  }
}

async function navigateMonth(offset: number) {
  const [year, monthValue] = month.value.split('-').map(Number)
  const next = new Date(year, monthValue - 1 + offset, 1)
  const nextMonth = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`
  if (nextMonth > currentMonth) return
  month.value = nextMonth
  const selectedInMonth = date.value.startsWith(nextMonth)
  if (!selectedInMonth) date.value = nextMonth === currentMonth ? today : `${nextMonth}-01`
  await loadMonth()
  await loadSelected()
}

async function selectDate(value: string) {
  if (isFutureDate(value)) return
  date.value = value
  const switchedMonth = !value.startsWith(month.value)
  if (switchedMonth) month.value = value.slice(0, 7)
  if (switchedMonth) await loadMonth()
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
    await loadMonth()
    await loadSelected()
    ElMessage.success('饮食记录已保存')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}
async function removeDiet(record: DietRecord) {
  try {
    await ElMessageBox.confirm('删除这条饮食记录？', '删除记录', { type: 'warning' })
    await deleteDietRecord(record.id)
    await loadMonth()
    await loadSelected()
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
    await loadMonth()
    await loadSelected()
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

onMounted(async () => {
  await loadMonth()
  await loadSelected()
})
</script>

<template>
  <div class="records-page page-wrapper">
    <header class="page-head records-head">
      <div>
        <span class="page-kicker">健康记录日历</span>
        <h1>你的健康节奏，有迹可循</h1>
        <p>红点代表热量超标，绿点代表目标内；食和动分别表示饮食与运动记录。</p>
      </div>
      <aside class="day-summary">
        <div><h2>{{ selectedDateText }}</h2></div>
        <div class="summary-energy"><strong class="num">{{ fmt(summary?.intake ?? 0) }}</strong><span>千卡摄入</span></div>
        <p class="summary-status" :class="selectedState?.status">{{ selectedState?.status === 'over_target' ? '摄入超过热量目标' : selectedState?.status === 'no_records' ? '当天还没有记录' : '摄入处于目标范围内' }}</p>
        <dl><div><dt>饮食</dt><dd>{{ dietRecords.length }} 条</dd></div><div><dt>运动</dt><dd>{{ exerciseRecords.length }} 条</dd></div><div><dt>消耗</dt><dd class="num">{{ fmt(summary?.burned ?? 0) }} kcal</dd></div></dl>
      </aside>
    </header>

    <section v-loading="monthLoading" class="calendar-layout">
      <article class="calendar-panel panel">
        <div class="calendar-title">
          <el-button circle plain aria-label="上一个月" @click="navigateMonth(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
          <div><h2>{{ monthLabel(month) }}</h2><p v-if="monthWarning">{{ monthWarning }}</p></div>
          <el-button circle plain aria-label="下一个月" :disabled="!canMoveForward" @click="navigateMonth(1)"><el-icon><ArrowRight /></el-icon></el-button>
        </div>
        <div class="week-row"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
        <div class="calendar-grid">
          <button v-for="value in calendarDates" :key="value" class="day-cell" :class="{ muted: !value.startsWith(month), selected: value === date, future: isFutureDate(value) }" :disabled="isFutureDate(value)" @click="selectDate(value)">
            <span class="day-number"><b>{{ Number(value.slice(-2)) }}</b><i :class="['status-dot', monthStates[value]?.status ?? 'no_records']" /></span>
            <span class="flags"><i v-if="monthStates[value]?.hasDiet" class="record-flag diet">食</i><i v-if="monthStates[value]?.hasExercise" class="record-flag exercise">动</i></span>
            <small v-if="monthStates[value]?.hasDiet" class="day-intake num">{{ fmt(monthStates[value].intake) }} kcal</small>
            <small v-else-if="value.startsWith(month)" class="day-intake empty">无记录</small>
          </button>
        </div>
        <div class="calendar-legend"><span><i class="status-dot over_target" />热量超标</span><span><i class="status-dot within_target" />目标内</span><span><i class="record-flag diet">食</i>饮食</span><span><i class="record-flag exercise">动</i>运动</span></div>
      </article>
    </section>

    <section v-loading="loading" class="record-detail">
      <div class="detail-head"><div><h2>当天记录</h2><p>{{ selectedDateText }} 的饮食与运动明细</p></div><el-radio-group v-model="tab" class="record-tabs"><el-radio-button value="diet">饮食</el-radio-button><el-radio-button value="exercise">运动</el-radio-button></el-radio-group></div>
      <div class="record-scroll">

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
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.records-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.records-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(350px, 380px);
  align-items: start;
  gap: 20px;
  margin-bottom: 18px;

  h1 {
    font-size: 32px;
  }

  .day-summary {
    position: relative;
    display: grid;
    grid-template-columns: minmax(136px, 1fr) auto;
    align-items: center;
    column-gap: 14px;
    row-gap: 5px;
    min-height: 0;
    padding: 14px 16px;
    border: 1px solid var(--primary-line);
    border-radius: var(--radius);
    background: var(--primary-soft);
    color: var(--ink);

    h2 {
      margin: 0;
      font-size: 17px;
    }

    .summary-energy {
      position: absolute;
      top: 14px;
      right: 16px;
      text-align: right;

      strong,
      span {
        display: block;
      }

      strong {
        color: var(--primary-deep);
        font-size: 26px;
        line-height: 1;
      }

      span {
        margin-top: 3px;
        color: var(--ink-3);
        font-size: 11px;
      }
    }

    .summary-status {
      grid-column: 1 / -1;
      display: inline-block;
      margin: 0;
      padding: 0;
      background: transparent;
      color: var(--ink-2);
      font-size: 12px;

      &.over_target {
        color: #c85c4c;
      }
    }

    dl {
      display: flex;
      grid-column: 1 / -1;
      gap: 20px;
      margin: 0;

      div {
        display: flex;
        flex: 1;
        justify-content: space-between;
        padding: 5px 0 0;
        border-top: 1px solid var(--primary-line);
        color: var(--ink-2);
        font-size: 12px;
      }
    }

    dt {
      color: var(--ink-3);
    }

    dd {
      margin: 0;
      color: var(--ink);
      font-weight: 700;
    }
  }
}

.calendar-layout {
  display: block;
  flex: none;
  margin-top: 0;
}

.calendar-panel {
  padding: 18px 22px 15px;
}

.calendar-title {
  display: grid;
  grid-template-columns: 40px 1fr 40px;
  align-items: center;
  justify-content: space-between;
  justify-items: center;

  h2 {
    margin: 0;
    font-size: 20px;
  }

  p {
    margin: 4px 0 0;
    color: var(--warn);
    font-size: 11px;
  }

  .el-icon {
    color: var(--primary-deep);
    font-size: 20px;
  }

  .el-button {
    --el-button-hover-bg-color: var(--primary-soft);
    --el-button-hover-border-color: var(--primary-line);
  }
}

.week-row,
.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 7px;
}

.week-row {
  margin: 14px 0 7px;

  span {
    color: var(--ink-3);
    text-align: center;
    font-size: 13px;
  }
}

.day-cell {
  min-width: 0;
  min-height: 78px;
  padding: 9px;
  border: 1px solid #e5ece7;
  border-radius: 7px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition:
    transform 0.16s,
    border-color 0.16s,
    box-shadow 0.16s;

  &:hover:not(:disabled) {
    transform: translateY(-2px);
    border-color: var(--primary);
    box-shadow: 0 5px 14px rgba(21, 128, 61, 0.08);
  }

  &:disabled {
    cursor: not-allowed;
  }

  &.selected {
    padding: 6px;
    border: 2px solid var(--primary);
    background: var(--primary-soft);
  }

  &.muted {
    opacity: 0.38;
  }

  &.future {
    opacity: 0.3;
    background: #fafcfb;
  }

  .day-number {
    display: flex;
    justify-content: space-between;
    align-items: center;

    b {
      font-size: 17px;
    }
  }

  .flags {
    display: flex;
    gap: 3px;
    min-height: 17px;
    margin-top: 8px;
  }

  .day-intake {
    display: block;
    overflow: hidden;
    margin-top: 5px;
    color: var(--ink-3);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;

    &.empty {
      color: #a3afa7;
    }
  }
}

.status-dot {
  width: 9px;
  height: 9px;
  display: inline-block;
  border-radius: 50%;
  background: #d7e1da;

  &.within_target {
    background: var(--primary);
  }

  &.over_target {
    background: var(--warn);
  }

  &.no_target {
    background: var(--info);
  }
}

.record-flag {
  width: 23px;
  height: 20px;
  display: inline-grid;
  place-items: center;
  border-radius: 3px;
  background: var(--primary-soft);
  color: var(--primary-deep);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;

  &.exercise {
    background: #eef6ff;
    color: var(--info);
  }
}

.calendar-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 11px;
  margin-top: 13px;
  color: var(--ink-3);
  font-size: 12px;

  span {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
}

.record-detail {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  margin-top: 18px;
}

.detail-head {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;

  h2 {
    margin: 0;
    font-size: 18px;
  }

  p {
    margin: 4px 0 0;
    color: var(--ink-3);
    font-size: 13px;
  }
}

.record-tabs {
  :deep(.el-radio-button__inner) {
    min-width: 76px;
    font-size: 13px;
  }
}

.record-scroll {
  min-height: 0;
  overflow-y: auto;
  padding: 0 4px 10px 0;
}

.record-card {
  padding: 17px;
  margin-top: 10px;

  header {
    display: flex;
    align-items: center;
    gap: 9px;

    > strong {
      margin-left: auto;
      color: var(--primary-deep);
      font-size: 14px;
    }
  }
}

.meal {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--meal-color) 10%, #fff);
  color: var(--meal-color);
  font-size: 11px;
  font-weight: 750;

  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--meal-color);
  }
}

.source {
  padding: 3px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--ink-3);
  font-size: 10px;
}

.record-actions {
  display: flex;
  gap: 2px;
}

.item-list {
  display: grid;
  gap: 0;
  margin-top: 13px;
  border-top: 1px solid var(--line);
}

.food-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);

  &:last-child {
    border-bottom: 0;
  }

  b,
  span {
    display: block;
  }

  b {
    font-size: 14px;
  }

  > div:first-child span {
    margin-top: 2px;
    color: var(--ink-3);
    font-size: 10px;
  }
}

.food-values {
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--ink-3);
  font-size: 11px;

  b {
    color: var(--ink);
  }
}

.exercise-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 17px;
  margin-top: 10px;

  b,
  small {
    display: block;
  }

  b {
    font-size: 13px;
  }

  small {
    margin-top: 2px;
    color: var(--ink-3);
    font-size: 10px;
  }

  > strong {
    margin-left: auto;
    color: var(--primary-deep);
    font-size: 14px;
  }
}

.exercise-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: #eef6ff;
  color: var(--info);
}

.empty-state {
  margin-top: 12px;
}

@media (max-width: 1000px) {
  .records-page {
    height: auto;
    overflow: visible;
  }

  .records-head {
    grid-template-columns: 1fr;

    .day-summary {
      max-width: none;
      min-height: 180px;
    }
  }

  .record-detail {
    min-height: auto;
  }

  .record-scroll {
    overflow: visible;
  }

  .day-cell {
    min-height: 82px;
  }
}

@media (max-width: 680px) {
  .records-head {
    display: grid;
    gap: 14px;

    h1 {
      font-size: 28px;
    }

    .day-summary {
      grid-template-columns: 1fr auto;
      min-height: auto;
      padding: 14px;

      dl {
        gap: 9px;
      }

      .summary-energy strong {
        font-size: 24px;
      }
    }
  }

  .calendar-panel {
    padding: 14px 12px 12px;
  }

  .calendar-title {
    grid-template-columns: 36px 1fr 36px;

    h2 {
      font-size: 17px;
    }
  }

  .week-row,
  .calendar-grid {
    gap: 4px;
  }

  .week-row span {
    font-size: 11px;
  }

  .day-cell {
    min-height: 66px;
    padding: 6px;

    &.selected {
      padding: 5px;
    }

    .day-number b {
      font-size: 12px;
    }

    .flags {
      min-height: 15px;
      margin-top: 5px;
    }

    .day-intake {
      margin-top: 4px;
      font-size: 8px;
    }
  }

  .record-flag {
    width: 17px;
    height: 15px;
    font-size: 8px;
  }

  .calendar-legend {
    gap: 9px;
    margin-top: 12px;
    font-size: 10px;
  }

  .detail-head {
    align-items: flex-end;
  }

  .record-tabs :deep(.el-radio-button__inner) {
    min-width: 62px;
  }

  .record-scroll {
    padding-right: 0;
  }

  .record-card header,
  .exercise-card {
    align-items: flex-start;
    flex-wrap: wrap;

    > strong {
      margin-left: 0;
    }
  }

  .record-actions,
  .exercise-card .record-actions {
    margin-left: auto;
  }

  .food-item {
    align-items: flex-start;
    flex-direction: column;
    gap: 7px;
  }

  .food-values {
    width: 100%;
    justify-content: space-between;
    gap: 8px;
  }
}
</style>
