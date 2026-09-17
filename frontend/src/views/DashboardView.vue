<script setup lang="ts">
// 今日健康操作台：基于既有 summary/trend API 呈现能量状态、宏量与历史趋势。
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, Food, MagicStick, PieChart, Timer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { EChartsCoreOption } from 'echarts/core'
import EChart from '@/components/EChart.vue'
import { getSummary, getTrend } from '@/api/dashboard'
import type { DailySummary, TrendPoint } from '@/types'
import { getErrorMessage } from '@/utils/error'

const summary = ref<DailySummary | null>(null)
const trend = ref<TrendPoint[]>([])
const loading = ref(false)

const css = getComputedStyle(document.documentElement)
const C = {
  intake: css.getPropertyValue('--viz-intake').trim() || '#16a34a',
  burned: css.getPropertyValue('--viz-burned').trim() || '#dd6f5b',
  carbs: css.getPropertyValue('--viz-carbs').trim() || '#4d8ccb',
  muted: css.getPropertyValue('--ink-3').trim() || '#76857b',
  line: css.getPropertyValue('--line').trim() || '#dce8df',
  surface: css.getPropertyValue('--bg-elevated').trim() || '#ffffff',
}

const fmt = (value: number) => Math.round(value).toLocaleString('zh-CN')
const todayLabel = new Intl.DateTimeFormat('zh-CN', {
  month: 'long', day: 'numeric', weekday: 'long',
}).format(new Date())
const target = computed(() => summary.value?.calorie_target ?? null)
const intake = computed(() => summary.value?.intake ?? 0)
const remaining = computed(() => summary.value?.remaining ?? null)
const overBudget = computed(() => remaining.value != null && remaining.value < 0)
const budgetPct = computed(() => {
  if (!target.value) return 0
  return Math.min(100, Math.max(0, (intake.value / target.value) * 100))
})
const displayRemaining = computed(() => remaining.value == null ? '—' : fmt(Math.abs(remaining.value)))
const energyLabel = computed(() => {
  if (target.value == null) return '等待设置目标'
  return overBudget.value ? '超出目标' : '剩余可摄入'
})
const heroTitle = computed(() => {
  if (target.value == null) return '先完善身体档案，建立今天的能量目标。'
  if (overBudget.value) return '今天已超过能量目标，管住嘴迈开腿！'
  return '今天的节奏不错，继续保持这份轻盈。'
})
const heroNote = computed(() => {
  if (target.value == null) return '完善身高、体重与目标后，NutriLens 会计算每日热量预算。'
  if (overBudget.value) return `当前超过目标 ${fmt(Math.abs(remaining.value ?? 0))} 千卡，尝试减少高油高糖加餐。`
  return `距离每日目标还可摄入 ${fmt(remaining.value ?? 0)} 千卡，优先补足蛋白质与蔬菜。`
})
const insight = computed(() => {
  if (target.value == null) return { title: '先建立你的能量基线', body: '填写身体档案后，助手才能结合你的目标给出更贴合的建议。', to: '/profile', action: '完善身体档案' }
  if (overBudget.value) return { title: '把接下来的选择放轻一些', body: '今天已超出热量目标，优先选择蔬菜、清汤和低脂蛋白质。', to: '/chat', action: '问问晚餐建议' }
  return { title: '晚餐还可以补一点蛋白质', body: '结合今天的摄入，优先选择鱼、鸡胸肉或无糖酸奶会更容易接近目标。', to: '/chat', action: '问问营养建议' }
})
const macroTotal = computed(() => {
  const macros = summary.value?.macros
  return macros ? macros.protein + macros.fat + macros.carbs : 0
})

const trendOption = computed<EChartsCoreOption>(() => ({
  tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => `${value} 千卡`, backgroundColor: C.surface, borderColor: C.line, borderWidth: 1, padding: [8, 12], textStyle: { color: C.muted, fontSize: 12 }, extraCssText: 'box-shadow: 0 10px 24px rgba(21,128,61,.08); border-radius: 8px;' },
  legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: C.muted, fontSize: 11 } },
  grid: { left: 42, right: 16, top: 20, bottom: 42 },
  xAxis: { type: 'category', boundaryGap: false, data: trend.value.map((item) => item.date.slice(5)), axisLine: { lineStyle: { color: C.line } }, axisTick: { show: false }, axisLabel: { color: C.muted, fontSize: 11 } },
  yAxis: { type: 'value', splitLine: { lineStyle: { color: '#edf3ee' } }, axisLabel: { color: C.muted, fontSize: 11 } },
  series: [
    { name: '摄入', type: 'line', data: trend.value.map((item) => item.intake), smooth: true, symbol: 'circle', symbolSize: 5, showSymbol: false, lineStyle: { width: 2.5, color: C.intake }, itemStyle: { color: C.intake }, areaStyle: { color: C.intake, opacity: 0.08 } },
    { name: '消耗', type: 'line', data: trend.value.map((item) => item.burned), smooth: true, symbol: 'circle', symbolSize: 5, showSymbol: false, lineStyle: { width: 2, color: C.burned }, itemStyle: { color: C.burned } },
    { name: '目标', type: 'line', data: trend.value.map((item) => item.calorie_target), symbol: 'none', lineStyle: { width: 1.5, type: 'dashed', color: C.muted }, itemStyle: { color: C.muted } },
  ],
}))

const macroOption = computed<EChartsCoreOption>(() => {
  const macros = summary.value?.macros
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 克（{d}%）', backgroundColor: C.surface, borderColor: C.line, borderWidth: 1, textStyle: { color: C.muted, fontSize: 12 } },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: C.muted, fontSize: 11 } },
    series: [{ type: 'pie', radius: ['57%', '76%'], center: ['50%', '44%'], data: macros ? [
      { name: '蛋白质', value: macros.protein, itemStyle: { color: C.intake } },
      { name: '脂肪', value: macros.fat, itemStyle: { color: C.burned } },
      { name: '碳水', value: macros.carbs, itemStyle: { color: C.carbs } },
    ] : [], label: { show: false }, itemStyle: { borderColor: C.surface, borderWidth: 3, borderRadius: 4 }, emphasis: { scale: false } }],
  }
})

async function load() {
  loading.value = true
  try {
    const [nextSummary, nextTrend] = await Promise.all([getSummary(), getTrend(7)])
    summary.value = nextSummary
    trend.value = nextTrend.series
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="dashboard-page page-wrapper">
    <header class="page-head dashboard-head">
      <div>
        <span class="page-kicker">每日健康工作台</span>
        <h1>今天，保持轻盈节奏</h1>
        <p>从饮食、运动与能量收支开始，照顾好今天的身体状态。</p>
      </div>
      <div class="today-stamp"><b>{{ todayLabel }}</b></div>
    </header>

    <section class="status-grid">
      <article class="daily-status">
        <span class="eyebrow hero-eyebrow">今日节奏</span>
        <h2>{{ heroTitle }}</h2>
        <p>{{ heroNote }}</p>
        <div class="hero-context"><span>今日重点</span><b>{{ target == null ? '建立能量基线' : overBudget ? '让晚餐更轻盈' : '优先补足蛋白质' }}</b></div>
        <div class="hero-actions">
          <router-link class="hero-button primary" to="/records">查看今日记录<el-icon><ArrowRight /></el-icon></router-link>
          <router-link class="hero-button secondary" to="/chat">问问 NutriLens</router-link>
        </div>
      </article>

      <article class="energy-card panel">
        <div class="energy-head"><span>今日能量预算</span><router-link to="/records">查看记录 <el-icon><ArrowRight /></el-icon></router-link></div>
        <div class="energy-main">
          <div class="energy-ring" :class="{ over: overBudget }" :style="{ '--progress': budgetPct + '%' }">
            <div><b class="num">{{ displayRemaining }}</b><span>{{ energyLabel }}</span></div>
          </div>
          <dl>
            <div><dt>已摄入</dt><dd class="num">{{ fmt(intake) }}</dd></div>
            <div><dt>运动消耗</dt><dd class="num">{{ fmt(summary?.burned ?? 0) }}</dd></div>
            <div><dt>目标摄入</dt><dd class="num">{{ target == null ? '—' : fmt(target) }}</dd></div>
          </dl>
        </div>
        <div class="macro-grid">
          <div><b class="num protein">{{ fmt(summary?.macros.protein ?? 0) }}g</b><span>蛋白质</span></div>
          <div><b class="num carbs">{{ fmt(summary?.macros.carbs ?? 0) }}g</b><span>碳水</span></div>
          <div><b class="num fat">{{ fmt(summary?.macros.fat ?? 0) }}g</b><span>脂肪</span></div>
        </div>
      </article>
    </section>

    <section class="quick-actions" aria-label="快捷操作">
      <router-link class="quick-action panel" to="/chat"><span class="quick-icon"><el-icon><Food /></el-icon></span><span><b>记录一餐</b><small>拍照或文字描述</small></span><el-icon class="quick-arrow"><ArrowRight /></el-icon></router-link>
      <router-link class="quick-action panel" to="/chat"><span class="quick-icon exercise"><el-icon><Timer /></el-icon></span><span><b>记录运动</b><small>跑步、力量或步行</small></span><el-icon class="quick-arrow"><ArrowRight /></el-icon></router-link>
      <router-link class="quick-action panel" to="/plan"><span class="quick-icon plan"><el-icon><MagicStick /></el-icon></span><span><b>生成计划</b><small>饮食与运动一起安排</small></span><el-icon class="quick-arrow"><ArrowRight /></el-icon></router-link>
    </section>

    <section class="dashboard-lower">
      <article class="panel chart-panel">
        <div class="panel-heading"><div><h2>近 7 日能量平衡</h2><p>薄荷绿代表摄入，珊瑚色代表运动消耗。</p></div><router-link to="/records">打开记录 →</router-link></div>
        <div class="chart"><EChart :option="trendOption" /></div>
      </article>
      <article class="panel insight-panel">
        <span class="insight-icon"><el-icon><MagicStick /></el-icon></span>
        <h2>AI 今日洞察</h2>
        <strong>{{ insight.title }}</strong>
        <p>{{ insight.body }}</p>
        <router-link :to="insight.to" class="insight-link">{{ insight.action }} <el-icon><ArrowRight /></el-icon></router-link>
      </article>
      <article class="panel macro-panel">
        <div class="panel-heading"><div><h2>营养摄入构成</h2><p>蛋白质、碳水、脂肪的已记录摄入量（克）</p></div></div>
        <div v-if="macroTotal > 0" class="donut-wrap"><EChart :option="macroOption" /><div class="donut-center"><b class="num">{{ fmt(macroTotal) }}</b><span>克 · 合计</span></div></div>
        <div v-else class="compact-empty"><el-icon><PieChart /></el-icon><span>记录饮食后，显示三种营养素的克数与占比</span></div>
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.dashboard-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.eyebrow {
  display: block;
  margin-bottom: 7px;
  color: var(--primary-deep);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.dashboard-head h1 {
  font-size: 32px;
}
.today-stamp {
  padding: 12px 14px;
  border: 1px solid var(--primary-line);
  border-radius: var(--radius);
  background: var(--primary-soft);
  text-align: right;
}
.today-stamp span,
.today-stamp b {
  display: block;
}
.today-stamp span {
  color: var(--primary-deep);
  font-size: 16px;
  font-weight: 700;
}
.today-stamp b {
  margin-top: 2px;
  color: var(--ink);
  font-size: 18px;
  color: var(--primary-deep);
}
.status-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(310px, 0.8fr);
  gap: 18px;
  margin-top: 26px;
}
.daily-status {
  position: relative;
  overflow: hidden;
  min-height: 326px;
  padding: 30px;
  border: 1px solid #11843d;
  border-radius: var(--radius);
  background: var(--primary);
  color: #fff;
  box-shadow: var(--shadow);
}
.daily-status::after {
  content: '';
  position: absolute;
  right: -62px;
  bottom: -92px;
  width: 294px;
  height: 294px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  box-shadow:
    0 0 0 31px rgba(255, 255, 255, 0.07),
    0 0 0 62px rgba(255, 255, 255, 0.035);
}
.daily-status > * {
  position: relative;
  z-index: 1;
}
.hero-eyebrow {
  color: #d9fbe4;
}
.daily-status h2 {
  max-width: 600px;
  margin: 12px 0 0;
  font-size: 31px;
  line-height: 1.17;
  letter-spacing: 0;
}
.daily-status p {
  max-width: 460px;
  margin: 11px 0 0;
  color: #e1f8e9;
  font-size: 14px;
}
.hero-context {
  display: inline-flex;
  gap: 9px;
  align-items: center;
  margin-top: 22px;
  padding: 7px 10px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.12);
  font-size: 12px;
}
.hero-context span {
  color: #d9fbe4;
}
.hero-context b {
  font-weight: 700;
}
.hero-actions {
  display: flex;
  gap: 8px;
  margin-top: 24px;
}
.hero-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 10px 13px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}
.hero-button.primary {
  background: #fff;
  border-color: #fff;
  color: var(--primary-deep);
}
.energy-card {
  padding: 23px;
  background: #fbfefb;
}
.energy-head,
.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.energy-head {
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.energy-head a {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.energy-head a,
.panel-heading a {
  color: var(--primary-deep);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: none;
}
.energy-main {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-top: 17px;
}
.energy-ring {
  position: relative;
  width: 140px;
  height: 140px;
  display: grid;
  place-items: center;
  flex: none;
  border-radius: 50%;
  background: conic-gradient(var(--primary) 0 var(--progress), #e7efe9 var(--progress) 100%);
}
.energy-ring.over {
  background: conic-gradient(var(--warn) 0 var(--progress), #f3e6e3 var(--progress) 100%);
}
.energy-ring::after {
  content: '';
  position: absolute;
  width: 101px;
  height: 101px;
  border-radius: 50%;
  background: var(--bg-elevated);
}
.energy-ring div {
  position: relative;
  z-index: 1;
  text-align: center;
}
.energy-ring b {
  display: block;
  font-size: 28px;
  line-height: 1;
}
.energy-ring span {
  display: block;
  max-width: 70px;
  margin-top: 4px;
  color: var(--ink-3);
  font-size: 11px;
  line-height: 1.25;
}
.energy-main dl {
  flex: 1;
  min-width: 0;
  margin: 0;
}
.energy-main dl div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 0;
  border-bottom: 1px solid #edf2ee;
  font-size: 13px;
}
.energy-main dl div:last-child {
  border: 0;
}
.energy-main dt {
  color: var(--ink-3);
}
.energy-main dd {
  margin: 0;
  font-weight: 700;
}
.macro-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 18px;
}
.macro-grid div {
  padding: 10px 5px;
  border-radius: 6px;
  background: #f2f8f3;
  text-align: center;
}
.macro-grid b,
.macro-grid span {
  display: block;
}
.macro-grid b {
  font-size: 14px;
}
.macro-grid span {
  margin-top: 3px;
  color: var(--ink-3);
  font-size: 11px;
}
.protein {
  color: var(--primary-deep);
}
.carbs {
  color: var(--info);
}
.fat {
  color: var(--warn);
}
.quick-actions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 18px;
}
.quick-action {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 16px;
  transition:
    transform 0.16s,
    border-color 0.16s,
    box-shadow 0.16s;
}
.quick-action:hover {
  transform: translateY(-2px);
  border-color: var(--primary-line);
  box-shadow: var(--shadow);
}
.quick-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: var(--primary-soft);
  color: var(--primary-deep);
}
.quick-icon.exercise {
  background: #eef6ff;
  color: var(--info);
}
.quick-icon.plan {
  background: #f3f0ff;
  color: #7565bd;
}
.quick-action b,
.quick-action small {
  display: block;
}
.quick-action b {
  color: var(--ink);
  font-size: 14px;
}
.quick-action small {
  margin-top: 2px;
  color: var(--ink-3);
  font-size: 12px;
}
.quick-arrow {
  margin-left: auto;
  color: var(--ink-3);
}
.dashboard-lower {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(220px, 0.62fr) minmax(280px, 0.76fr);
  gap: 18px;
  margin-top: 22px;
}
.chart-panel,
.insight-panel,
.macro-panel {
  padding: 22px;
}
.panel-heading h2,
.insight-panel h2 {
  margin: 0;
  font-size: 17px;
}
.panel-heading p {
  margin: 4px 0 0;
  color: var(--ink-3);
  font-size: 12px;
}
.chart {
  height: 260px;
}
.insight-panel {
  background: var(--primary-soft);
  border-color: var(--primary-line);
}
.insight-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: var(--primary);
  color: #fff;
}
.insight-panel h2 {
  margin-top: 14px;
}
.insight-panel strong {
  display: block;
  margin-top: 17px;
  font-size: 20px;
  line-height: 1.25;
}
.insight-panel p {
  margin: 8px 0 0;
  color: var(--ink-2);
  font-size: 13px;
}
.insight-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 18px;
  color: var(--primary-deep);
  font-size: 12px;
  font-weight: 750;
}
.donut-wrap {
  position: relative;
  height: 260px;
}
.donut-center {
  position: absolute;
  inset: 0 0 42px;
  display: grid;
  place-content: center;
  text-align: center;
  pointer-events: none;
}
.donut-center b {
  font-size: 25px;
}
.donut-center span {
  margin-top: 3px;
  color: var(--ink-3);
  font-size: 11px;
}
.compact-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 220px;
  color: var(--ink-3);
  font-size: 12px;
}
.compact-empty .el-icon {
  color: var(--line-strong);
  font-size: 26px;
}
@media (max-width: 1080px) {
  .status-grid,
  .dashboard-lower {
    grid-template-columns: 1fr;
  }
  .insight-panel {
    min-height: 190px;
  }
}
@media (max-width: 680px) {
  .dashboard-head {
    display: block;
  }
  .today-stamp {
    width: fit-content;
    margin-top: 14px;
    text-align: left;
  }
  .status-grid {
    margin-top: 18px;
  }
  .daily-status {
    min-height: 290px;
    padding: 22px;
  }
  .daily-status h2 {
    font-size: 27px;
  }
  .energy-main {
    gap: 12px;
  }
  .energy-ring {
    width: 114px;
    height: 114px;
  }
  .energy-ring::after {
    width: 82px;
    height: 82px;
  }
  .energy-ring b {
    font-size: 22px;
  }
  .quick-actions {
    grid-template-columns: 1fr;
  }
  .chart {
    height: 230px;
  }
}
</style>
