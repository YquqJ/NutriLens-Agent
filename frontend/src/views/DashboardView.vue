<script setup lang="ts">
// 看板页：热量预算进度 + 收支指标卡 + 7 日趋势 + 宏量环图。
// 数据源：/dashboard/summary（单日）+ /dashboard/trend（近 7 天）。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSummary, getTrend } from '@/api/dashboard'
import { getErrorMessage } from '@/utils/error'
import { todayISO } from '@/utils/date'
import EChart from '@/components/EChart.vue'
import type { EChartsCoreOption } from 'echarts/core'
import type { DailySummary, TrendPoint } from '@/types'

const date = ref(todayISO())
const summary = ref<DailySummary | null>(null)
const trend = ref<TrendPoint[]>([])
const loading = ref(false)

// 图表色板单一来源：读 CSS 变量，与设计系统保持一致
const css = getComputedStyle(document.documentElement)
const C = {
  intake: css.getPropertyValue('--viz-intake').trim() || '#22c55e',
  burned: css.getPropertyValue('--viz-burned').trim() || '#fb923c',
  carbs: css.getPropertyValue('--viz-carbs').trim() || '#38bdf8',
  target: css.getPropertyValue('--ink-3').trim() || '#8a8e88',
  line: css.getPropertyValue('--line').trim() || '#e7e5e0',
}

const fmt = (n: number) => Math.round(n).toLocaleString('zh-CN')

// ---- 热量预算（签名元素：今日还剩多少可吃）----
const target = computed(() => summary.value?.calorie_target ?? null)
const intake = computed(() => summary.value?.intake ?? 0)
const remaining = computed(() => summary.value?.remaining ?? null)
const overBudget = computed(() => remaining.value != null && remaining.value < 0)
const budgetPct = computed(() => {
  const t = target.value
  if (!t) return 0
  return Math.min(100, Math.max(0, (intake.value / t) * 100))
})
const remainingText = computed(() => (remaining.value != null ? fmt(remaining.value) : '—'))
const targetText = computed(() => (target.value != null ? fmt(target.value) : '—'))
const heroNoteText = computed(() => {
  if (target.value == null) return ''
  return overBudget.value
    ? `已超出目标 ${fmt(intake.value - target.value)} 千卡`
    : `目标 ${fmt(target.value)} 千卡`
})

// ---- 净收支 ----
const net = computed(() => summary.value?.net ?? 0)
const netSigned = computed(() => {
  const n = net.value
  if (Math.abs(n) < 0.5) return '0'
  return n > 0 ? `+${fmt(n)}` : `−${fmt(-n)}`
})
const netStatus = computed(() => {
  const n = net.value
  if (Math.abs(n) < 0.5) return { text: '平衡', cls: '' }
  return n > 0 ? { text: '盈余', cls: 'warn' } : { text: '缺口', cls: 'ok' }
})

// ---- 指标卡文案 ----
const intakeText = computed(() => (summary.value ? fmt(summary.value.intake) : '—'))
const burnedText = computed(() => (summary.value ? fmt(summary.value.burned) : '—'))
const intakeSubText = computed(() => {
  if (target.value == null) return '未设目标'
  const pct = Math.round((intake.value / target.value) * 100)
  return `目标 ${fmt(target.value)} · 已用 ${pct}%`
})

const macroTotal = computed(() => {
  const m = summary.value?.macros
  return m ? m.protein + m.fat + m.carbs : 0
})

// 趋势折线 option
const trendOption = computed<EChartsCoreOption>(() => ({
  tooltip: {
    trigger: 'axis',
    valueFormatter: (v: unknown) => `${v} 千卡`,
    backgroundColor: '#ffffff',
    borderColor: C.line,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: '#1a1d1a', fontSize: 12 },
    extraCssText: 'box-shadow: 0 6px 20px rgba(26,29,26,0.08); border-radius: 8px;',
  },
  legend: {
    bottom: 0,
    icon: 'circle',
    itemWidth: 8,
    itemHeight: 8,
    textStyle: { color: C.target, fontSize: 11 },
  },
  grid: { left: 44, right: 16, top: 20, bottom: 44 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: trend.value.map((t) => t.date.slice(5)),
    axisLine: { lineStyle: { color: C.line } },
    axisTick: { show: false },
    axisLabel: { color: C.target, fontSize: 11 },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: '#f0eeea' } },
    axisLabel: { color: C.target, fontSize: 11 },
  },
  series: [
    {
      name: '摄入',
      type: 'line',
      data: trend.value.map((t) => t.intake),
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: false,
      lineStyle: { width: 2, color: C.intake },
      itemStyle: { color: C.intake },
      areaStyle: { color: C.intake, opacity: 0.07 },
    },
    {
      name: '消耗',
      type: 'line',
      data: trend.value.map((t) => t.burned),
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
      showSymbol: false,
      lineStyle: { width: 2, color: C.burned },
      itemStyle: { color: C.burned },
    },
    {
      name: '目标',
      type: 'line',
      data: trend.value.map((t) => t.calorie_target),
      symbol: 'none',
      lineStyle: { width: 1.5, type: 'dashed', color: C.target },
      itemStyle: { color: C.target },
    },
  ],
}))

// 宏量环图 option（环心合计由模板 HTML 覆盖层渲染，避免 echarts 居中文本的定位问题）
const macroOption = computed<EChartsCoreOption>(() => {
  const m = summary.value?.macros
  const data = m
    ? [
        { name: '蛋白质', value: m.protein, itemStyle: { color: C.intake } },
        { name: '脂肪', value: m.fat, itemStyle: { color: C.burned } },
        { name: '碳水', value: m.carbs, itemStyle: { color: C.carbs } },
      ]
    : []
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 克（{d}%）',
      backgroundColor: '#ffffff',
      borderColor: C.line,
      borderWidth: 1,
      textStyle: { color: '#1a1d1a', fontSize: 12 },
      extraCssText: 'box-shadow: 0 6px 20px rgba(26,29,26,0.08); border-radius: 8px;',
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: C.target, fontSize: 11 },
    },
    series: [
      {
        type: 'pie',
        radius: ['56%', '76%'],
        center: ['50%', '44%'],
        data,
        label: { show: false },
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 4 },
        emphasis: { scale: false },
      },
    ],
  }
})

async function load() {
  loading.value = true
  try {
    const [s, t] = await Promise.all([getSummary(date.value), getTrend(7)])
    summary.value = s
    trend.value = t.series
  } catch (e) {
    ElMessage.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h1>看板</h1>
        <p>今天的能量收支与营养摄入。</p>
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

    <!-- 热量预算：今日还剩多少可吃 -->
    <section class="panel hero">
      <div class="hero-left">
        <span class="hero-label">今日剩余可摄入</span>
        <div class="hero-value" :class="{ over: overBudget }">
          <span class="num">{{ remainingText }}</span>
          <span class="hero-unit">千卡</span>
        </div>
        <div class="hero-note" :class="{ over: overBudget }">{{ heroNoteText }}</div>
        <router-link v-if="target == null" class="hero-cta" to="/profile">去设置档案</router-link>
      </div>

      <div class="hero-right">
        <template v-if="target != null">
          <div class="bar">
            <div class="bar-fill" :class="{ over: overBudget }" :style="{ width: budgetPct + '%' }" />
          </div>
          <div class="bar-legend">
            <span class="num">已摄入 {{ intakeText }}</span>
            <span class="num">目标 {{ targetText }}</span>
          </div>
        </template>
        <template v-else>
          <div class="bar bar-empty" />
          <div class="bar-legend muted">完善身体档案后自动计算每日预算</div>
        </template>
      </div>
    </section>

    <!-- 收支指标卡 -->
    <div class="metrics">
      <div class="panel metric">
        <div class="m-head">
          <span class="m-icon intake"><el-icon><KnifeFork /></el-icon></span>
          <span class="m-label">摄入</span>
        </div>
        <div class="m-value num">{{ intakeText }}</div>
        <div class="m-sub">{{ intakeSubText }}</div>
      </div>
      <div class="panel metric">
        <div class="m-head">
          <span class="m-icon burned"><el-icon><Lightning /></el-icon></span>
          <span class="m-label">消耗</span>
        </div>
        <div class="m-value num">{{ burnedText }}</div>
        <div class="m-sub">基础代谢 + 运动</div>
      </div>
      <div class="panel metric">
        <div class="m-head">
          <span class="m-icon net"><el-icon><Odometer /></el-icon></span>
          <span class="m-label">净收支</span>
        </div>
        <div class="m-value num" :class="netStatus.cls">{{ netSigned }}</div>
        <div class="m-sub" :class="netStatus.cls">{{ netStatus.text }} · 摄入 − 消耗</div>
      </div>
    </div>

    <!-- 图表区 -->
    <div class="charts">
      <section class="panel chart-card">
        <h2 class="card-title">近 7 日趋势</h2>
        <div class="chart"><EChart :option="trendOption" /></div>
      </section>

      <section class="panel chart-card">
        <h2 class="card-title">宏量营养素（克）</h2>
        <div v-if="macroTotal > 0" class="chart donut-wrap">
          <EChart :option="macroOption" />
          <div class="donut-center">
            <span class="dc-val num">{{ fmt(macroTotal) }}</span>
            <span class="dc-label">克 · 合计</span>
          </div>
        </div>
        <div v-else class="empty-state">
          <el-icon class="es-icon"><PieChart /></el-icon>
          <span class="es-title">暂无数据</span>
          <span class="es-hint">记录饮食后，这里会显示宏量构成</span>
        </div>
      </section>
    </div>
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

/* ---- 热量预算 hero ---- */
.hero {
  display: flex;
  align-items: center;
  gap: 40px;
  padding: 22px 26px;
  margin-bottom: 16px;
}
.hero-left {
  flex: none;
  min-width: 200px;
}
.hero-label {
  font-size: 13px;
  color: var(--ink-3);
}
.hero-value {
  margin-top: 4px;
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--primary-deep);
}
.hero-value .num {
  font-size: 40px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1;
}
.hero-value.over .num {
  color: var(--warn);
}
.hero-unit {
  font-size: 13px;
  color: var(--ink-3);
}
.hero-note {
  margin-top: 8px;
  font-size: 13px;
  color: var(--ink-2);
}
.hero-note.over {
  color: var(--warn);
}
.hero-cta {
  display: inline-block;
  margin-top: 14px;
  padding: 7px 16px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
}
.hero-cta:hover {
  background: var(--primary-deep);
}

.hero-right {
  flex: 1;
  min-width: 0;
}
.bar {
  height: 14px;
  border-radius: 999px;
  background: var(--bg);
  border: 1px solid var(--line);
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--primary);
  transition: width 0.4s ease;
}
.bar-fill.over {
  background: var(--warn);
}
.bar-empty {
  background: var(--bg);
}
.bar-legend {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--ink-3);
}
.bar-legend.muted {
  justify-content: flex-start;
}

/* ---- 指标卡 ---- */
.metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.metric {
  padding: 18px 20px;
}
.m-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.m-icon {
  width: 28px;
  height: 28px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 7px;
  font-size: 15px;
}
.m-icon.intake {
  color: var(--viz-intake);
  background: color-mix(in srgb, var(--viz-intake) 12%, #fff);
}
.m-icon.burned {
  color: var(--viz-burned);
  background: color-mix(in srgb, var(--viz-burned) 12%, #fff);
}
.m-icon.net {
  color: var(--ink-2);
  background: var(--bg);
}
.m-label {
  font-size: 13px;
  color: var(--ink-3);
}
.m-value {
  margin-top: 10px;
  font-size: 30px;
  font-weight: 650;
  letter-spacing: -0.01em;
  line-height: 1;
}
.m-value.warn {
  color: var(--warn);
}
.m-value.ok {
  color: var(--primary-deep);
}
.m-sub {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-3);
}
.m-sub.warn {
  color: var(--warn);
}
.m-sub.ok {
  color: var(--primary-deep);
}

/* ---- 图表 ---- */
.charts {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 20px;
}
.chart-card {
  padding: 20px;
}
.card-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
}
.chart {
  height: 300px;
}
.donut-wrap {
  position: relative;
}
.donut-center {
  position: absolute;
  inset: 0;
  bottom: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  pointer-events: none;
}
.dc-val {
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.dc-label {
  font-size: 12px;
  color: var(--ink-3);
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
    align-items: stretch;
    gap: 20px;
  }
  .metrics {
    grid-template-columns: 1fr;
  }
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>
