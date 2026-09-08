<script setup lang="ts">
// ECharts 轻量封装：按需注册图表/组件，监听窗口 resize 自适应，option 变化时增量更新。
// 用 echarts/core 树摇，避免把整包拖进主 bundle。
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'

echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ option: EChartsCoreOption }>()

const el = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

function resize() {
  chart?.resize()
}

onMounted(() => {
  chart = echarts.init(el.value!)
  chart.setOption(props.option)
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})

watch(
  () => props.option,
  (o) => chart?.setOption(o, true),
  { deep: true },
)
</script>

<template>
  <div ref="el" class="echart" />
</template>

<style scoped>
.echart {
  width: 100%;
  height: 100%;
}
</style>
