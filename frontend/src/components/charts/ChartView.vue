<template>
  <div class="chart-container" v-if="hasData">
    <div class="chart-header">
      <span class="chart-title">{{ title }}</span>
    </div>
    <v-chart
      :option="mergedOption"
      :autoresize="true"
      style="height: 320px"
      ref="chartRef"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  MarkPointComponent,
  MarkLineComponent,
} from 'echarts/components'

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

const props = defineProps<{
  option: any
  title?: string
}>()

const chartRef = ref()

const hasData = computed(() => props.option && Object.keys(props.option).length > 0)

const mergedOption = computed(() => {
  const baseOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(17, 17, 19, 0.96)',
      borderColor: 'rgba(255, 255, 255, 0.08)',
      borderWidth: 1,
      padding: [12, 16],
      textStyle: { color: '#FAFAFA', fontSize: 13, fontFamily: 'var(--font-sans)' },
      extraCssText: 'box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5); border-radius: 8px;',
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '12%',
      containLabel: true,
    },
    backgroundColor: 'transparent',
    textStyle: {
      color: '#71717A',
      fontFamily: 'var(--font-sans)',
    },
  }

  const result = {
    ...props.option,
    ...baseOption,
    ...props.option,
    tooltip: { ...baseOption.tooltip, ...props.option?.tooltip },
    grid: { ...baseOption.grid, ...props.option?.grid },
  }

  if (props.option?.xAxis) {
    result.xAxis = {
      ...props.option.xAxis,
      axisLine: { lineStyle: { color: 'rgba(113, 113, 122, 0.2)' } },
      axisLabel: { color: '#71717A', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(113, 113, 122, 0.06)' } },
    }
  }

  if (props.option?.yAxis) {
    result.yAxis = {
      ...props.option.yAxis,
      axisLine: { lineStyle: { color: 'rgba(113, 113, 122, 0.2)' } },
      axisLabel: { color: '#71717A', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(113, 113, 122, 0.06)' } },
    }
  }

  if (props.option?.legend) {
    result.legend = {
      ...props.option.legend,
      textStyle: { color: '#A1A1AA', fontSize: 12 },
    }
  }

  return result
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  padding: 16px;
  background: var(--bg-1);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.chart-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-1);
  letter-spacing: 0.01em;
}
</style>
