<template>
  <div v-if="hasData" class="chart-container">
    <div class="chart-header">
      <span class="chart-title">{{ title || '查询结果可视化' }}</span>
      <span class="chart-kind">{{ chartType }}</span>
    </div>
    <VChart :option="mergedOption" :autoresize="true" class="chart-canvas" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import type { EChartsCoreOption } from 'echarts/core'

import type { EChartsOption } from '../../api/types'

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  PieChart,
  ScatterChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  MarkPointComponent,
  MarkLineComponent,
])

const props = withDefaults(
  defineProps<{
    option: EChartsOption
    title?: string
    chartType?: string
  }>(),
  { title: '', chartType: '' },
)

const PALETTE = ['#6366F1', '#8B5CF6', '#22D3EE', '#F472B6', '#FBBF24', '#4ADE80', '#FB923C']

const hasData = computed(() => Boolean(props.option) && Object.keys(props.option).length > 0)

const chartType = computed(() => props.chartType || String(props.option?.chart_type ?? ''))

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

/** 后端只给 series/xAxis 等业务配置，这里补齐暗色主题的坐标轴、提示框、网格。 */
const mergedOption = computed<EChartsCoreOption>(() => {
  const source = props.option ?? {}
  const baseTooltip = {
    trigger: 'axis',
    backgroundColor: 'rgba(17, 17, 19, 0.96)',
    borderColor: 'rgba(255, 255, 255, 0.08)',
    borderWidth: 1,
    padding: [10, 14],
    textStyle: { color: '#FAFAFA', fontSize: 12 },
    extraCssText: 'box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5); border-radius: 8px;',
  }
  const baseGrid = { left: '3%', right: '4%', bottom: '3%', top: '14%', containLabel: true }
  const axisStyle = {
    axisLine: { lineStyle: { color: 'rgba(113, 113, 122, 0.25)' } },
    axisLabel: { color: '#71717A', fontSize: 11 },
    splitLine: { lineStyle: { color: 'rgba(113, 113, 122, 0.07)' } },
    axisTick: { show: false },
  }

  const merged: Record<string, unknown> = {
    color: PALETTE,
    backgroundColor: 'transparent',
    textStyle: { color: '#71717A', fontSize: 12 },
    ...source,
    tooltip: { ...baseTooltip, ...asRecord(source.tooltip) },
    grid: { ...baseGrid, ...asRecord(source.grid) },
  }

  if (source.xAxis) {
    const axis = Array.isArray(source.xAxis) ? source.xAxis : [source.xAxis]
    merged.xAxis = axis.map((item) => ({ ...axisStyle, ...asRecord(item) }))
  }
  if (source.yAxis) {
    const axis = Array.isArray(source.yAxis) ? source.yAxis : [source.yAxis]
    merged.yAxis = axis.map((item) => ({ ...axisStyle, ...asRecord(item) }))
  }
  if (source.legend) {
    merged.legend = { textStyle: { color: '#A1A1AA', fontSize: 12 }, ...asRecord(source.legend) }
  }
  delete merged.chart_type

  return merged as EChartsCoreOption
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  padding: 14px 16px 8px;
  background: var(--bg-1);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.chart-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-1);
  letter-spacing: 0.01em;
}

.chart-kind {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--fg-3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.chart-canvas {
  width: 100%;
  height: 320px;
}
</style>
