<template>
  <div class="reports-view">
    <div class="page-header">
      <div class="header-left">
        <h1>分析报告</h1>
        <p class="page-desc">从对话生成 Markdown 报告并下载</p>
      </div>
      <div v-if="reportContent" class="header-actions">
        <button class="btn-secondary" @click="downloadReport">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M7 2v8m0 0l-2.5-2.5M7 10l2.5-2.5M2 11v.5a1.5 1.5 0 001.5 1.5h7A1.5 1.5 0 0012 11.5V11" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          下载 Markdown
        </button>
      </div>
    </div>

    <div class="generator-card">
      <div class="generator-icon">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <path d="M10 2l2.5 5 5.5.8-4 3.9.9 5.5L10 14.8 5.1 17.2 6 11.7 2 7.8l5.5-.8L10 2z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="generator-content">
        <div class="generator-field">
          <label class="generator-label">选择对话记录</label>
          <t-select
            v-model="selectedConvId"
            placeholder="选择要生成报告的对话"
            :options="convOptions"
            style="width: 380px"
            class="report-select"
          />
        </div>
      </div>
      <button
        class="btn-primary"
        :disabled="!selectedConvId"
        @click="generateReport"
        :loading="generating"
      >
        <template v-if="!generating">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M1 7l13-5-5 13-3-4-5-4z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round" fill="currentColor" fill-opacity="0.2"/>
          </svg>
          生成报告
        </template>
        <template v-else>生成中...</template>
      </button>
    </div>

    <div v-if="reportContent" class="report-preview-wrap">
      <div class="preview-header">
        <div class="preview-title">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <rect x="2" y="2" width="10" height="10" rx="1.5" stroke="currentColor" stroke-width="1.1"/>
            <path d="M4.5 5.5h5M4.5 7.5h5M4.5 9.5h3" stroke="currentColor" stroke-width="1" stroke-linecap="round"/>
          </svg>
          <span>报告预览</span>
        </div>
      </div>
      <div class="report-preview markdown-content" v-html="renderMarkdown(reportContent)">
      </div>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">
        <svg width="44" height="44" viewBox="0 0 44 44" fill="none">
          <rect x="6" y="4" width="20" height="32" rx="3" stroke="currentColor" stroke-width="1.5"/>
          <path d="M16 4v32" stroke="currentColor" stroke-width="1.5"/>
          <path d="M28 12h8M28 19h8M28 26h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </div>
      <h3>还没有生成报告</h3>
      <p>选择一段对话记录，点击生成报告按钮开始创建分析报告</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { marked } from 'marked'
import { api } from '../api/client'
import { useChatStore } from '../stores/chat'

const chat = useChatStore()
const selectedConvId = ref('')
const reportContent = ref('')
const generating = ref(false)

const convOptions = computed(() =>
  chat.conversations.map((c) => ({ label: c.title || '新对话', value: c.id }))
)

onMounted(() => {
  chat.fetchConversations()
})

function renderMarkdown(text: string): string {
  return marked(text, { breaks: true }) as string
}

async function generateReport() {
  if (!selectedConvId.value) return
  generating.value = true
  try {
    const res = await api.post('/reports/generate', {
      conversation_id: selectedConvId.value,
      format: 'markdown',
    })
    reportContent.value = res.data
  } catch (e: any) {
    console.error('Report generation failed:', e)
  } finally {
    generating.value = false
  }
}

function downloadReport() {
  if (!reportContent.value) return
  const blob = new Blob([reportContent.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `report-${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.reports-view {
  padding: 32px 48px;
  max-width: 1200px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 32px;
}

.header-left h1 {
  font-size: 24px;
  font-weight: 600;
  color: var(--fg-0);
  letter-spacing: -0.02em;
}

.page-desc {
  font-size: 14px;
  color: var(--fg-2);
  margin-top: 6px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 18px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-dim);
}

.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-2);
  color: var(--fg-1);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.btn-secondary:hover {
  background: var(--bg-3);
  border-color: var(--border-strong);
}

.generator-card {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px 24px;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 24px;
}

.generator-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-hi);
  border-radius: var(--radius-sm);
  color: var(--accent);
  flex-shrink: 0;
}

.generator-content {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 16px;
}

.generator-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.generator-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--fg-3);
}

.report-preview-wrap {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.preview-header {
  display: flex;
  align-items: center;
  padding: 16px 24px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
}

.preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-2);
}

.preview-title svg {
  color: var(--accent);
}

.report-preview {
  padding: 28px;
  min-height: 300px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 40px;
  text-align: center;
  color: var(--fg-2);
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.empty-icon {
  color: var(--fg-3);
  margin-bottom: 24px;
  display: flex;
}

.empty-state h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--fg-1);
  margin-bottom: 8px;
}

.empty-state p {
  font-size: 13px;
  color: var(--fg-3);
  max-width: 320px;
  line-height: 1.6;
}

:deep(.t-select) {
  background: var(--bg-2) !important;
  border-color: var(--border) !important;
}

:deep(.t-select__wrap) {
  background: var(--bg-2) !important;
}
</style>
