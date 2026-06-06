<template>
  <div class="chat-panel" ref="panelRef">
    <!-- 空状态 -->
    <div v-if="messages.length === 0" class="chat-empty">
      <div class="empty-icon">◆</div>
      <h2>有什么数据问题需要分析？</h2>
      <p class="empty-hint">试试这些提问：</p>
      <div class="hint-list">
        <button
          v-for="hint in hints"
          :key="hint"
          class="hint-chip"
          @click="$emit('send', hint)"
        >
          {{ hint }}
        </button>
      </div>
    </div>

    <!-- 消息列表 -->
    <div v-else class="chat-messages">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="message"
        :class="msg.role"
      >
        <div class="msg-avatar">
          <t-avatar v-if="msg.role === 'user'" size="small">👤</t-avatar>
          <span v-else class="ai-avatar">◆</span>
        </div>
        <div class="msg-body">
          <!-- Markdown 渲染 -->
          <div
            class="msg-content markdown-content"
            v-html="renderMarkdown(msg.content)"
          ></div>

          <!-- SQL 展示 -->
          <div v-if="msg.metadata?.sql" class="msg-sql">
            <div class="sql-header">
              <span class="sql-label">📋 SQL 查询</span>
              <button class="sql-copy-btn" @click="copySQL(msg.metadata.sql, $event)">复制</button>
            </div>
            <pre class="sql-block"><code>{{ msg.metadata.sql }}</code></pre>
          </div>

          <!-- 图表 -->
          <div v-if="msg.metadata?.chart_config?.echarts_option" class="msg-chart">
            <ChartView :option="msg.metadata.chart_config.echarts_option" :title="msg.metadata.chart_config.title" />
          </div>

          <!-- 诊断建议 -->
          <div v-if="msg.metadata?.diagnosis_suggestions?.length" class="msg-suggestions">
            <div class="suggestion-title">💡 优化建议</div>
            <div
              v-for="(s, i) in msg.metadata.diagnosis_suggestions"
              :key="i"
              class="suggestion-item"
            >
              {{ s }}
            </div>
          </div>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-if="isStreaming" class="message assistant">
        <div class="msg-avatar">
          <span class="ai-avatar pulse">◆</span>
        </div>
        <div class="msg-body">
          <div class="typing-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { marked } from 'marked'
import ChartView from '../charts/ChartView.vue'
import type { Message } from '../../stores/chat'

const props = defineProps<{
  messages: Message[]
  isStreaming: boolean
}>()

defineEmits<{
  send: [text: string]
}>()

const panelRef = ref<HTMLElement>()

const hints = [
  '上个月哪个产品亏损最多？',
  '过去6个月销售额趋势如何？',
  '各渠道ROI对比分析',
  '帮我看看哪些产品毛利率低于20%',
]

function renderMarkdown(text: string): string {
  return marked(text, { breaks: true }) as string
}

function copySQL(sql: string, event: Event) {
  navigator.clipboard.writeText(sql).then(() => {
    const btn = event.target as HTMLElement
    btn.textContent = '✓ 已复制'
    setTimeout(() => { btn.textContent = '复制' }, 1500)
  })
}

// 自动滚到底部
watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (panelRef.value) {
      panelRef.value.scrollTop = panelRef.value.scrollHeight
    }
  }
)
</script>

<style scoped>
.chat-panel {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

/* Empty State */
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
}

.empty-icon {
  font-size: 48px;
  color: var(--accent);
  filter: drop-shadow(0 0 16px var(--accent-glow));
  margin-bottom: 20px;
}

.chat-empty h2 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.empty-hint {
  font-size: 14px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.hint-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  max-width: 500px;
}

.hint-chip {
  padding: 8px 16px;
  border-radius: 20px;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.hint-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--bg-hover);
}

/* Messages */
.chat-messages {
  max-width: 800px;
  margin: 0 auto;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  animation: msgIn 0.3s ease;
}

@keyframes msgIn {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg-avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-avatar {
  font-size: 20px;
  color: var(--accent);
}
.ai-avatar.pulse {
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.msg-body {
  flex: 1;
  min-width: 0;
}

.msg-content {
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  padding: 14px 18px;
  line-height: 1.7;
}

.message.user .msg-content {
  background: var(--bg-hover);
  border: 1px solid var(--border);
}

.msg-sql {
  margin-top: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.sql-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg-hover);
  border-bottom: 1px solid var(--border);
}

.sql-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}

.sql-copy-btn {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.sql-copy-btn:hover {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.sql-block {
  margin: 0;
  padding: 14px 16px;
  background: #0d1117;
  overflow-x: auto;
  white-space: pre;
  line-height: 1.6;
}
.sql-block code {
  font-family: var(--font-mono);
  font-size: 13px;
  color: #c9d1d9;
  background: none;
  padding: 0;
}

.msg-chart {
  margin-top: 12px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  padding: 16px;
}

.msg-suggestions {
  margin-top: 12px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  padding: 14px 18px;
  border-left: 3px solid var(--success);
}

.suggestion-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--success);
}

.suggestion-item {
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

/* Typing dots */
.typing-dots {
  display: flex;
  gap: 6px;
  padding: 14px 18px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
  width: fit-content;
}

.typing-dots span {
  width: 8px;
  height: 8px;
  background: var(--accent);
  border-radius: 50%;
  animation: dotBounce 1.4s infinite both;
}

.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
</style>
