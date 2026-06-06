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

const mergedOption = computed(() => ({
  ...props.option,
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#1e3044',
    borderColor: '#2a4259',
    textStyle: { color: '#e8edf2', fontSize: 13 },
    ...props.option?.tooltip,
  },
  grid: {
    left: '3%',
    right: '4%',
    bottom: '3%',
    containLabel: true,
    ...props.option?.grid,
  },
}))
</script>

<style scoped>
.chart-container {
  width: 100%;
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.chart-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
</style>
