<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1 class="page-title">分析报告</h1>
        <p class="page-desc">
          从任意对话生成一份结构化报告：问题、结论、SQL、诊断建议与结果数据。生成后可预览 Markdown，并下载 Markdown / HTML / PDF。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn btn-secondary" type="button" :disabled="loadingReports" @click="loadReports">
          <span v-if="loadingReports" class="spinner"></span>
          刷新列表
        </button>
      </div>
    </header>

    <section class="card generator">
      <div class="generator-icon">
        <svg width="19" height="19" viewBox="0 0 20 20" fill="none">
          <path d="M10 2l2.4 4.9 5.4.8-3.9 3.8.9 5.4L10 14.4 5.2 16.9l.9-5.4L2.2 7.7l5.4-.8L10 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" />
        </svg>
      </div>

      <div class="generator-main">
        <label class="field generator-field">
          <span class="label">选择对话记录</span>
          <select v-model="selectedConvId" class="select" :disabled="generating || !conversations.length">
            <option value="">{{ conversations.length ? '请选择要生成报告的对话' : '暂无对话，请先到「对话」提问' }}</option>
            <option v-for="conversation in conversations" :key="conversation.id" :value="conversation.id">
              {{ conversation.title || '新对话' }}
            </option>
          </select>
        </label>
        <p class="hint">
          报告会落库保存，列表里可以反复下载；不会修改原始对话。
        </p>
      </div>

      <button
        class="btn btn-primary generate-btn"
        type="button"
        :disabled="!selectedConvId || generating || !canGenerate"
        :title="canGenerate ? '' : '当前角色缺少 report:generate 权限'"
        @click="generate"
      >
        <span v-if="generating" class="spinner"></span>
        {{ generating ? '生成中…' : '生成报告' }}
      </button>
    </section>

    <ErrorAlert
      v-if="generateError"
      class="block-gap"
      :error="generateError"
      title="生成报告失败"
      retryable
      @retry="generate"
      @dismiss="generateError = null"
    />

    <ErrorAlert
      v-if="downloadError"
      class="block-gap"
      :error="downloadError"
      title="下载失败"
      @dismiss="downloadError = null"
    />

    <section class="card">
      <div class="card-head">
        <span class="card-title">已生成的报告</span>
        <span class="card-sub">{{ reports.length }} 份</span>
      </div>

      <div v-if="loadingReports" class="skeleton-list">
        <div v-for="index in 3" :key="index" class="skeleton-row">
          <div class="skeleton skeleton-line" style="width: 42%"></div>
          <div class="skeleton skeleton-line" style="width: 18%"></div>
        </div>
      </div>

      <ErrorAlert
        v-else-if="reportsError"
        class="inline-alert"
        :error="reportsError"
        title="无法加载报告列表"
        retryable
        @retry="loadReports"
        @dismiss="reportsError = null"
      />

      <div v-else-if="!reports.length" class="empty">
        <div class="empty-icon">
          <svg width="42" height="42" viewBox="0 0 44 44" fill="none">
            <rect x="8" y="4" width="20" height="32" rx="3" stroke="currentColor" stroke-width="1.5" />
            <path d="M18 4v32" stroke="currentColor" stroke-width="1.5" />
            <path d="M28 12h8M28 19h8M28 26h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </div>
        <h3>还没有生成报告</h3>
        <p>选择一段对话并点击「生成报告」，它会出现在这里，支持 Markdown / HTML / PDF 下载。</p>
      </div>

      <ul v-else class="report-list">
        <li
          v-for="report in reports"
          :key="report.id"
          class="report-item"
          :class="{ active: previewReport?.id === report.id }"
        >
          <button class="report-main" type="button" @click="preview(report)">
            <span class="report-icon">
              <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M4 1.5h5l3.5 3.5v9A1 1 0 0111.5 15h-7A1 1 0 013.5 14V2.5A1 1 0 014 1.5z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round" />
                <path d="M9 1.5V5h3.5M6 8h4M6 10.5h4M6 13h2.5" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>
            <span class="report-meta">
              <span class="report-title truncate">{{ report.title }}</span>
              <span class="report-sub mono">{{ formatDate(report.created_at) }} · {{ shortId(report.id) }}</span>
            </span>
          </button>

          <div class="report-actions">
            <button class="btn btn-sm btn-ghost" type="button" @click="preview(report)">预览</button>
            <button
              v-for="format in formats"
              :key="format.value"
              class="btn btn-sm btn-secondary"
              type="button"
              :disabled="downloading === `${report.id}:${format.value}`"
              @click="download(report, format.value)"
            >
              <span v-if="downloading === `${report.id}:${format.value}`" class="spinner"></span>
              {{ format.label }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="previewReport || previewLoading" class="card preview-card">
      <div class="card-head">
        <div class="preview-title">
          <span class="card-title">报告预览</span>
          <span v-if="previewReport" class="card-sub">{{ previewReport.title }}</span>
        </div>
        <div class="row">
          <button
            v-for="format in formats"
            :key="format.value"
            class="btn btn-sm btn-secondary"
            type="button"
            :disabled="!previewReport || downloading === `${previewReport.id}:${format.value}`"
            @click="previewReport && download(previewReport, format.value)"
          >
            <span
              v-if="previewReport && downloading === `${previewReport.id}:${format.value}`"
              class="spinner"
            ></span>
            下载 {{ format.label }}
          </button>
          <button class="btn btn-sm btn-ghost" type="button" @click="closePreview">关闭</button>
        </div>
      </div>

      <div v-if="previewLoading" class="preview-skeleton">
        <div class="skeleton skeleton-line" style="width: 36%; height: 16px"></div>
        <div class="skeleton skeleton-line" style="width: 92%"></div>
        <div class="skeleton skeleton-line" style="width: 86%"></div>
        <div class="skeleton skeleton-line" style="width: 74%"></div>
        <div class="skeleton" style="height: 120px; margin-top: 12px"></div>
      </div>

      <ErrorAlert
        v-else-if="previewError"
        class="inline-alert"
        :error="previewError"
        title="预览失败"
        @dismiss="previewError = null"
      />

      <div v-else-if="previewReport" class="preview-body markdown-content" v-html="renderedMarkdown"></div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { conversationApi, reportApi, toApiError, type ApiError } from '../api/client'
import type {
  ConversationSummary,
  ReportDetail,
  ReportFormat,
  ReportSummary,
} from '../api/types'
import ErrorAlert from '../components/ui/ErrorAlert.vue'
import { renderMarkdown } from '../lib/markdown'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const canGenerate = computed(() => auth.has('report:generate'))

const formats: { value: ReportFormat; label: string }[] = [
  { value: 'markdown', label: 'MD' },
  { value: 'html', label: 'HTML' },
  { value: 'pdf', label: 'PDF' },
]

const conversations = ref<ConversationSummary[]>([])
const selectedConvId = ref('')
const generating = ref(false)
const generateError = ref<ApiError | null>(null)

const reports = ref<ReportSummary[]>([])
const loadingReports = ref(true)
const reportsError = ref<ApiError | null>(null)

const previewReport = ref<ReportDetail | null>(null)
const previewLoading = ref(false)
const previewError = ref<ApiError | null>(null)

const downloading = ref('')
const downloadError = ref<ApiError | null>(null)

const renderedMarkdown = computed(() => renderMarkdown(previewReport.value?.markdown ?? ''))

onMounted(() => {
  void loadConversations()
  void loadReports()
})

async function loadConversations(): Promise<void> {
  try {
    conversations.value = await conversationApi.list()
  } catch (caught) {
    generateError.value = toApiError(caught)
  }
}

async function loadReports(): Promise<void> {
  loadingReports.value = true
  reportsError.value = null
  try {
    reports.value = await reportApi.list()
  } catch (caught) {
    reportsError.value = toApiError(caught)
  } finally {
    loadingReports.value = false
  }
}

async function generate(): Promise<void> {
  if (!selectedConvId.value || generating.value) return
  generating.value = true
  generateError.value = null
  try {
    const result = await reportApi.generate({
      conversation_id: selectedConvId.value,
      format: 'json',
    })
    const created: ReportSummary = {
      id: result.id,
      title: result.title,
      conversation_id: selectedConvId.value,
      created_at: result.created_at,
    }
    reports.value = [created, ...reports.value.filter((item) => item.id !== created.id)]
    await preview(created)
  } catch (caught) {
    generateError.value = toApiError(caught)
  } finally {
    generating.value = false
  }
}

async function preview(report: ReportSummary): Promise<void> {
  previewLoading.value = true
  previewError.value = null
  previewReport.value = null
  try {
    previewReport.value = await reportApi.get(report.id)
  } catch (caught) {
    previewError.value = toApiError(caught)
  } finally {
    previewLoading.value = false
  }
}

function closePreview(): void {
  previewReport.value = null
  previewError.value = null
}

async function download(report: ReportSummary, format: ReportFormat): Promise<void> {
  const key = `${report.id}:${format}`
  if (downloading.value) return
  downloading.value = key
  downloadError.value = null
  try {
    const file = await reportApi.download(report.id, format)
    const url = URL.createObjectURL(file.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = file.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 2000)
  } catch (caught) {
    downloadError.value = toApiError(caught)
  } finally {
    downloading.value = ''
  }
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  const normalized = iso.includes('T') && !/[Z+-]\d/.test(iso.slice(10)) ? `${iso}Z` : iso
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (input: number): string => String(input).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function shortId(id: string): string {
  return id.slice(0, 8)
}
</script>

<style scoped>
.generator {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 18px 20px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}

.generator-icon {
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--accent-hi);
  border: 1px solid var(--accent-line);
  color: var(--accent);
  flex-shrink: 0;
}

.generator-main {
  flex: 1;
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.generator-field {
  max-width: 460px;
}

.generate-btn {
  align-self: flex-start;
  height: 36px;
}

.block-gap {
  margin-bottom: 16px;
}

.inline-alert {
  margin: 14px 18px;
}

.skeleton-list {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.skeleton-row {
  display: flex;
  gap: 28px;
}

.skeleton-row .skeleton-line {
  margin: 0;
}

.report-list {
  list-style: none;
  display: flex;
  flex-direction: column;
}

.report-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
  transition: background var(--dur-1);
}

.report-item:last-child {
  border-bottom: none;
}

.report-item:hover {
  background: rgba(255, 255, 255, 0.018);
}

.report-item.active {
  background: var(--accent-hi);
}

.report-main {
  display: flex;
  align-items: center;
  gap: 11px;
  border: none;
  background: transparent;
  color: inherit;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  min-width: 0;
  flex: 1;
  padding: 0;
}

.report-icon {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--bg-3);
  color: var(--fg-2);
  flex-shrink: 0;
}

.report-item.active .report-icon {
  background: var(--accent-hi);
  color: var(--accent);
}

.report-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.report-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--fg-0);
  max-width: 520px;
}

.report-sub {
  font-size: 10.5px;
  color: var(--fg-4);
}

.report-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.preview-card {
  margin-top: 18px;
}

.preview-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.preview-body {
  padding: 24px 28px 32px;
  max-height: 640px;
  overflow-y: auto;
}

.preview-skeleton {
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

@media (max-width: 900px) {
  .report-item {
    flex-direction: column;
    align-items: stretch;
  }
  .report-actions {
    justify-content: flex-end;
    flex-wrap: wrap;
  }
}
</style>
