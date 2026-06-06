<template>
  <div class="reports-view">
    <div class="page-header">
      <h2>分析报告</h2>
      <p class="subtitle">从对话生成 Markdown 报告并下载</p>
    </div>

    <div class="report-generator">
      <t-select
        v-model="selectedConvId"
        placeholder="选择对话记录"
        :options="convOptions"
        style="width: 360px"
      />
      <t-button theme="primary" :disabled="!selectedConvId" @click="generateReport" :loading="generating">
        <t-icon name="download" /> 导出 Markdown
      </t-button>
    </div>

    <div v-if="reportContent" class="report-preview markdown-content" v-html="renderMarkdown(reportContent)">
    </div>

    <div v-if="reportContent" class="report-actions">
      <t-button theme="primary" @click="downloadReport">
        <t-icon name="download" /> 下载 Markdown
      </t-button>
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

    const content = res.data
    reportContent.value = content
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
  a.download = `report-${new Date().toISOString().slice(0,10)}.md`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.reports-view {
  padding: 24px 32px;
  max-width: 1000px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
  margin-top: 4px;
}

.report-generator {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  margin-bottom: 24px;
}

.report-preview {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  padding: 24px 32px;
  min-height: 200px;
  margin-bottom: 16px;
}

.report-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
