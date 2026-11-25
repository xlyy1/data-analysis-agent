<template>
  <div class="answer-blocks">
    <div v-if="warnings.length" class="warn-block">
      <div class="block-head">
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M7 1.8L12.6 11.6H1.4L7 1.8z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round" />
          <path d="M7 5.4v2.6M7 9.9v.2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
        <span>数据提示</span>
      </div>
      <ul class="warn-list">
        <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>

    <div v-if="sql" class="sql-block-wrap">
      <div class="block-head sql-head">
        <div class="sql-label">
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <ellipse cx="7" cy="3" rx="5" ry="1.5" stroke="currentColor" stroke-width="1.1" />
            <path d="M2 3v3.5c0 .8 2.2 1.5 5 1.5s5-.7 5-1.5V3" stroke="currentColor" stroke-width="1.1" />
            <path d="M2 6.5V10c0 .8 2.2 1.5 5 1.5s5-.7 5-1.5V6.5" stroke="currentColor" stroke-width="1.1" />
          </svg>
          <span>生成的 SQL</span>
        </div>
        <button class="btn btn-sm btn-ghost copy-btn" type="button" @click="copySql">
          {{ copied ? '已复制' : '复制' }}
        </button>
      </div>
      <pre class="sql-code"><code>{{ sql }}</code></pre>
      <details v-if="executedSql && executedSql !== sql" class="executed">
        <summary>查看实际执行 SQL（含自动补的 LIMIT）</summary>
        <pre class="sql-code"><code>{{ executedSql }}</code></pre>
      </details>
    </div>

    <ChartView
      v-if="hasChart"
      :option="chartOption"
      :title="chartTitle"
      :chart-type="chartKind"
    />

    <div v-if="columns.length" class="result-table card">
      <div class="card-head">
        <span class="card-title">查询结果</span>
        <span class="card-sub">{{ rows.length }} 行 × {{ columns.length }} 列</span>
      </div>
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th v-for="(column, index) in columns" :key="`${column}-${index}`">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
              <td v-for="(cell, cellIndex) in row" :key="cellIndex" class="cell" :class="{ numeric: isNumber(cell) }">
                {{ formatCell(cell) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!rows.length" class="cell-empty">查询返回 0 行数据</div>
    </div>

    <div v-if="suggestions.length" class="suggest-block">
      <div class="block-head">
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <circle cx="7" cy="7" r="5.6" stroke="currentColor" stroke-width="1.1" />
          <path d="M7 4v3.6M7 9.4v.2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
        </svg>
        <span>改进建议</span>
      </div>
      <ul class="suggest-list">
        <li v-for="(suggestion, index) in suggestions" :key="index">{{ suggestion }}</li>
      </ul>
    </div>

    <div v-if="options.length" class="options-block">
      <div class="options-title">请选择要继续的方向：</div>
      <div class="options-list">
        <button
          v-for="option in options"
          :key="option"
          class="option-btn"
          type="button"
          @click="$emit('send', option)"
        >
          <span>{{ option }}</span>
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>

    <div v-if="traceId" class="trace-line">trace_id: {{ traceId }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import ChartView from '../charts/ChartView.vue'
import type { CellValue, ChatMessage, EChartsOption } from '../../api/types'

const props = defineProps<{ message: ChatMessage }>()

defineEmits<{ send: [text: string] }>()

const copied = ref(false)

const metadata = computed(() => props.message.metadata ?? {})
const sql = computed(() => (metadata.value.sql ?? '').trim())
const executedSql = computed(() => (metadata.value.executed_sql ?? '').trim())
const warnings = computed(() => metadata.value.result_warnings ?? [])
const suggestions = computed(() => metadata.value.diagnosis_suggestions ?? [])
const options = computed(() => props.message.options ?? [])
const traceId = computed(() => metadata.value.trace_id ?? '')

const chartOption = computed<EChartsOption>(() => {
  const config = metadata.value.chart_config
  return config?.echarts_option ?? {}
})
const chartTitle = computed(() => metadata.value.chart_config?.title ?? '')
const chartKind = computed(() => metadata.value.chart_config?.chart_type ?? '')
const hasChart = computed(() => Object.keys(chartOption.value).length > 0)

const columns = computed<string[]>(() => metadata.value.data_columns ?? [])
const rows = computed<CellValue[][]>(() => {
  const source = metadata.value.data_rows ?? []
  const width = columns.value.length
  if (!width) return []
  return source.slice(0, 20).map((row) => {
    const next = Array.isArray(row) ? [...row] : []
    while (next.length < width) next.push(null)
    return next.slice(0, width)
  })
})

function isNumber(value: CellValue): boolean {
  return typeof value === 'number'
}

function formatCell(value: CellValue): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

async function copySql(): Promise<void> {
  const text = sql.value
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    document.body.removeChild(area)
  }
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1600)
}
</script>

<style scoped>
.answer-blocks {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}

.block-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 600;
  color: var(--fg-2);
  padding: 8px 14px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
}

.block-head svg {
  color: var(--accent);
}

.warn-block,
.suggest-block {
  border: 1px solid rgba(251, 191, 36, 0.22);
  border-radius: var(--radius);
  background: rgba(251, 191, 36, 0.05);
  overflow: hidden;
}

.warn-block .block-head,
.suggest-block .block-head {
  background: transparent;
  border-bottom: none;
  padding-bottom: 4px;
  color: var(--warning);
}

.warn-list,
.suggest-list {
  margin: 0;
  padding: 0 16px 12px 30px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.warn-list li,
.suggest-list li {
  font-size: 12.5px;
  color: var(--fg-2);
  line-height: 1.65;
}

.suggest-block {
  border-color: var(--accent-line);
  background: var(--accent-hi);
}

.suggest-block .block-head {
  color: #A5B4FC;
}

.sql-block-wrap {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg-1);
}

.sql-head {
  justify-content: space-between;
  background: var(--bg-2);
}

.sql-label {
  display: flex;
  align-items: center;
  gap: 7px;
}

.sql-label svg {
  color: var(--accent);
}

.copy-btn {
  color: var(--fg-3);
}

.sql-code {
  margin: 0;
  padding: 13px 16px;
  background: var(--bg-0);
  overflow-x: auto;
  white-space: pre;
  line-height: 1.65;
}

.sql-code code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--fg-1);
}

.executed {
  border-top: 1px solid var(--border);
  background: var(--bg-1);
}

.executed summary {
  padding: 8px 16px;
  font-size: 11.5px;
  color: var(--fg-3);
  cursor: pointer;
  user-select: none;
}

.executed summary:hover {
  color: var(--fg-1);
}

.result-table {
  border-radius: var(--radius);
}

.result-table .card-head {
  padding: 9px 14px;
}

.cell {
  font-family: var(--font-mono);
  font-size: 12px;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell.numeric {
  text-align: right;
  color: var(--fg-0);
}

.cell-empty {
  padding: 14px;
  text-align: center;
  font-size: 12px;
  color: var(--fg-3);
}

.options-block {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-1);
  padding: 12px 14px;
}

.options-title {
  font-size: 12px;
  color: var(--fg-3);
  margin-bottom: 8px;
}

.options-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.option-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--border-strong);
  background: var(--bg-2);
  color: var(--fg-1);
  font-family: var(--font-sans);
  font-size: 12.5px;
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}

.option-btn svg {
  color: var(--fg-3);
  transition: transform var(--dur-1) var(--ease-out), color var(--dur-1);
}

.option-btn:hover {
  border-color: var(--border-accent);
  background: var(--accent-hi);
  color: #C7D2FE;
}

.option-btn:hover svg {
  color: var(--accent);
  transform: translateX(2px);
}

.trace-line {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--fg-4);
  word-break: break-all;
}
</style>
