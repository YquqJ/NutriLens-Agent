<script setup lang="ts">
// 看板页：单日热量收支 + 宏量营养素环图 + 7 日趋势折线。
// 数据源：/dashboard/summary（单日）+ /dashboard/trend（近 7 天）。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSummary, getTrend } from '@/api/dashboard'
import { getErrorMessage } from '@/utils/error'
import EChart from '@/components/EChart.vue'
import type { EChartsCoreOption } from 'echarts/core'
import type { DailySummary, TrendPoint } from '@/types'

const date = ref(new Date().toISOString().slice(0, 10))
const summary = ref<DailySummary | null>(null)
const trend = ref<TrendPoint[]>([])
const loading = ref(false)

// 与设计系统对齐的克制色板
const C = { intake: '#0e7a5f', burned: '#c8861f', target: '#8a8e88', line: '#e7e5e0' }

const macroTotal = computed(() => {
  const m = summary.value?.macros
  return m ? m.protein + m.fat + m.carbs : 0
})

const netLabel = computed(() => {
  if (!summary.value) return '—'
  const n = summary.value.net
  if (Math.abs(n) < 0.5) return '平衡'
  return n > 0 ? `盈余 ${Math.round(n)}` : `缺口 ${Math.round(-n)}`
})
const netClass = computed(() => {
  if (!summary.value) return ''
  return summary.value.net > 0.5 ? 'warn' : 'ok'
})

// 趋势折线 option
const trendOption = computed<EChartsCoreOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8 },
  grid: { left: 44, right: 16, top: 16, bottom: 44 },
  xAxis: {
    type: 'category',
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
      lineStyle: { width: 2, color: C.intake },
      itemStyle: { color: C.intake },
    },
    {
      name: '消耗',
      type: 'line',
      data: trend.value.map((t) => t.burned),
      smooth: true,
      symbol: 'circle',
      symbolSize: 5,
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

// 宏量环图 option
const macroOption = computed<EChartsCoreOption>(() => {
  const m = summary.value?.macros
  const data = m
    ? [
        { name: '蛋白质', value: m.protein, itemStyle: { color: C.intake } },
        { name: '脂肪', value: m.fat, itemStyle: { color: C.burned } },
        { name: '碳水', value: m.carbs, itemStyle: { color: '#3a6b8f' } },
      ]
    : []
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 克（{d}%）' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8 },
    series: [
      {
        type: 'pie',
        radius: ['58%', '78%'],
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
      <h1>看板</h1>
      <p>热量收支与营养摄入概览。</p>
      <el-date-picker
        v-model="date"
        type="date"
        value-format="YYYY-MM-DD"
        :clearable="false"
        size="small"
        class="date-pick"
        @change="load"
      />
    </div>

    <!-- 热量收支：四张指标卡 -->
    <div class="metrics">
      <div class="panel metric">
        <div class="m-label">摄入</div>
        <div class="m-value num">{{ summary ? Math.round(summary.intake) : '—' }}</div>
        <div class="m-unit">千卡</div>
      </div>
      <div class="panel metric">
        <div class="m-label">消耗</div>
        <div class="m-value num">{{ summary ? Math.round(summary.burned) : '—' }}</div>
        <div class="m-unit">千卡</div>
      </div>
      <div class="panel metric">
        <div class="m-label">净收支</div>
        <div class="m-value num" :class="netClass">{{ netLabel }}</div>
        <div class="m-unit">摄入 − 消耗</div>
      </div>
      <div class="panel metric">
        <div class="m-label">剩余可摄入</div>
        <div class="m-value num">
          {{ summary?.remaining != null ? Math.round(summary.remaining) : '—' }}
        </div>
        <div class="m-unit">千卡</div>
      </div>
    </div>

    <!-- 图表区 -->
    <div class="charts">
      <section class="panel chart-card">
        <h2 class="card-title">近 7 日趋势</h2>
        <div class="chart trend"><EChart :option="trendOption" /></div>
      </section>

      <section class="panel chart-card">
        <h2 class="card-title">宏量营养素（克）</h2>
        <div v-if="macroTotal > 0" class="chart donut"><EChart :option="macroOption" /></div>
        <div v-else class="empty">今日暂无饮食记录</div>
      </section>
    </div>

    <p v-if="summary && summary.calorie_target == null" class="tip">
      尚未设置热量目标，去「档案」完善身体数据后即可计算每日建议摄入。
    </p>
  </div>
</template>

<style scoped>
.page-head {
  position: relative;
}
.date-pick {
  position: absolute;
  right: 0;
  top: 0;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.metric {
  padding: 18px 20px;
}
.m-label {
  font-size: 13px;
  color: var(--ink-3);
}
.m-value {
  margin-top: 6px;
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.m-value.warn {
  color: var(--warn);
}
.m-value.ok {
  color: var(--primary-deep);
}
.m-unit {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-3);
}

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
.empty {
  height: 300px;
  display: grid;
  place-items: center;
  color: var(--ink-3);
  font-size: 13px;
}
.tip {
  margin: 16px 0 0;
  padding: 12px 16px;
  background: var(--primary-soft);
  border-radius: var(--radius-sm);
  color: var(--primary-deep);
  font-size: 13px;
}
</style>
