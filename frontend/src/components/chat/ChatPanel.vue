<template>
  <div class="chat-panel" ref="panelRef">
    <div v-if="messages.length === 0" class="chat-empty">
      <div class="empty-icon">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect x="6" y="6" width="16" height="16" rx="3" fill="currentColor"/>
          <rect x="26" y="6" width="16" height="10" rx="3" fill="currentColor" opacity="0.4"/>
          <rect x="6" y="26" width="16" height="10" rx="3" fill="currentColor" opacity="0.4"/>
          <rect x="26" y="18" width="16" height="16" rx="3" fill="currentColor" opacity="0.7"/>
        </svg>
      </div>
      <h1 class="empty-title">你好, 我是 DataAgent</h1>
      <p class="empty-sub">用自然语言提问，我来帮你查询数据、生成分析和可视化图表</p>
      <div class="hint-grid">
        <button
          v-for="(hint, index) in hints"
          :key="hint"
          class="hint-card"
          :style="{ animationDelay: `${index * 60}ms` }"
          @click="$emit('send', hint)"
        >
          <span class="hint-text">{{ hint }}</span>
          <span class="hint-arrow">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </span>
        </button>
      </div>
    </div>

    <div v-else class="chat-messages">
      <transition-group name="msg">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message"
          :class="msg.role"
        >
          <div class="msg-avatar">
            <div v-if="msg.role === 'user'" class="user-avatar">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="4.5" r="2.5" fill="currentColor"/>
                <path d="M2 12.5c0-2.5 2-4 5-4s5 1.5 5 4" fill="currentColor"/>
              </svg>
            </div>
            <div v-else class="ai-avatar">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect x="1" y="1" width="5" height="5" rx="1.2" fill="currentColor"/>
                <rect x="8" y="1" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4"/>
                <rect x="1" y="8" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4"/>
                <rect x="8" y="6" width="5" height="5" rx="1.2" fill="currentColor" opacity="0.7"/>
              </svg>
            </div>
          </div>
          <div class="msg-body">
            <div class="msg-content-wrap">
              <div
                class="msg-content markdown-content"
                :class="msg.role"
                v-html="renderMarkdown(msg.content)"
              ></div>
            </div>

            <div v-if="msg.metadata?.sql" class="msg-sql">
              <div class="sql-header">
                <div class="sql-label">
                  <span class="sql-icon">
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <ellipse cx="7" cy="3" rx="5" ry="1.5" stroke="currentColor" stroke-width="1.1"/>
                      <path d="M2 3v3.5c0 .8 2.2 1.5 5 1.5s5-.7 5-1.5V3" stroke="currentColor" stroke-width="1.1"/>
                      <path d="M2 6.5V10c0 .8 2.2 1.5 5 1.5s5-.7 5-1.5V6.5" stroke="currentColor" stroke-width="1.1"/>
                    </svg>
                  </span>
                  <span class="sql-title">生成的 SQL 查询</span>
                </div>
                <button class="sql-copy" @click="copySQL(msg.metadata.sql, $event)">
                  <span class="copy-text">复制</span>
                </button>
              </div>
              <pre class="sql-block"><code>{{ msg.metadata.sql }}</code></pre>
            </div>

            <div v-if="msg.metadata?.chart_config?.echarts_option" class="msg-chart">
              <ChartView :option="msg.metadata.chart_config.echarts_option" :title="msg.metadata.chart_config.title" />
            </div>

            <div v-if="msg.metadata?.diagnosis_suggestions?.length" class="msg-suggestions">
              <div class="suggestion-title">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.1"/>
                  <path d="M7 4v4M7 9.5v.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                </svg>
                <span>优化建议</span>
              </div>
              <div
                v-for="(s, i) in msg.metadata.diagnosis_suggestions"
                :key="i"
                class="suggestion-item"
              >
                <span class="suggestion-bullet"></span>
                {{ s }}
              </div>
            </div>
          </div>
        </div>
      </transition-group>

      <transition name="msg">
        <div v-if="isStreaming" class="message assistant" key="streaming">
          <div class="msg-avatar">
            <div class="ai-avatar pulse">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect x="1" y="1" width="5" height="5" rx="1.2" fill="currentColor"/>
                <rect x="8" y="1" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4"/>
                <rect x="1" y="8" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4"/>
                <rect x="8" y="6" width="5" height="5" rx="1.2" fill="currentColor" opacity="0.7"/>
              </svg>
            </div>
          </div>
          <div class="msg-body">
            <div class="typing">
              <div class="typing-dots">
                <span></span><span></span><span></span>
              </div>
              <span class="typing-label">正在分析数据</span>
            </div>
          </div>
        </div>
      </transition>
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
  '上个月销售额排名前5的产品是哪些?',
  '分析各地区的客户增长率趋势',
  '找出毛利率低于15%的产品类别',
  '对比不同渠道的获客成本和转化率',
]

function renderMarkdown(text: string): string {
  return marked(text, { breaks: true }) as string
}

function copySQL(sql: string, event: Event) {
  navigator.clipboard.writeText(sql).then(() => {
    const btn = event.currentTarget as HTMLElement
    const textEl = btn.querySelector('.copy-text')
    if (textEl) textEl.textContent = '已复制'
    setTimeout(() => {
      if (textEl) textEl.textContent = '复制'
    }, 1500)
  })
}

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
  padding: 32px 48px;
}

.chat-panel::-webkit-scrollbar {
  width: 6px;
}
.chat-panel::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
}

.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  max-width: 560px;
  margin: 0 auto;
}

.empty-icon {
  color: var(--accent);
  margin-bottom: 32px;
  opacity: 0.85;
}

.empty-title {
  font-size: 28px;
  font-weight: 600;
  color: var(--fg-0);
  margin-bottom: 10px;
  letter-spacing: -0.03em;
}

.empty-sub {
  font-size: 14px;
  color: var(--fg-2);
  margin-bottom: 40px;
  line-height: 1.7;
  max-width: 400px;
}

.hint-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  width: 100%;
}

.hint-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-1);
  color: var(--fg-1);
  font-size: 13px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
  text-align: left;
  animation: hintIn 500ms var(--ease-out) both;
}

.hint-text {
  flex: 1;
  text-align: left;
}

.hint-arrow {
  color: var(--fg-3);
  display: flex;
  flex-shrink: 0;
  transition: transform var(--dur-2) var(--ease-out), color var(--dur-2);
}

.hint-card:hover {
  border-color: var(--border-strong);
  background: var(--bg-3);
  transform: translateY(-1px);
}

.hint-card:hover .hint-arrow {
  color: var(--accent);
  transform: translateX(2px);
}

@keyframes hintIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.chat-messages {
  max-width: 800px;
  margin: 0 auto;
}

.message {
  display: flex;
  gap: 14px;
  margin-bottom: 24px;
}

.msg-avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-avatar {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--bg-3);
  color: var(--fg-2);
}

.ai-avatar {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--accent-hi);
  color: var(--accent);
}

.ai-avatar.pulse {
  animation: aiPulse 1.4s ease-in-out infinite;
}

@keyframes aiPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

.msg-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.msg-content-wrap {
  display: flex;
}

.message.user .msg-content-wrap {
  justify-content: flex-end;
}

.msg-content {
  border-radius: var(--radius);
  padding: 14px 18px;
  line-height: 1.7;
  font-size: 14px;
  max-width: 100%;
}

.msg-content.assistant {
  background: var(--bg-1);
  border: 1px solid var(--border);
  color: var(--fg-1);
  border-top-left-radius: var(--radius-sm);
}

.msg-content.user {
  background: var(--accent);
  color: #ffffff;
  border: none;
  border-top-right-radius: var(--radius-sm);
}

.msg-content.user :deep(p),
.msg-content.user :deep(li),
.msg-content.user :deep(strong) {
  color: #ffffff;
}

.msg-sql {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--bg-1);
}

.sql-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
}

.sql-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sql-icon {
  display: flex;
  color: var(--accent);
}

.sql-title {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--fg-2);
}

.sql-copy {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--fg-3);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
  font-family: var(--font-sans);
}

.sql-copy:hover {
  background: var(--bg-3);
  color: var(--fg-1);
  border-color: var(--border-strong);
}

.sql-block {
  margin: 0;
  padding: 14px 16px;
  background: var(--bg-0);
  overflow-x: auto;
  white-space: pre;
  line-height: 1.6;
}

.sql-block code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--fg-1);
  background: none;
  padding: 0;
}

.msg-chart {
  background: var(--bg-1);
  border-radius: var(--radius);
  padding: 16px;
  border: 1px solid var(--border);
}

.msg-suggestions {
  background: var(--bg-1);
  border-radius: var(--radius);
  padding: 14px 18px;
  border: 1px solid var(--border);
  border-left: 2px solid var(--accent);
}

.suggestion-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-2);
  margin-bottom: 10px;
}

.suggestion-title svg {
  color: var(--accent);
}

.suggestion-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 4px 0;
  font-size: 13px;
  color: var(--fg-2);
  line-height: 1.6;
}

.suggestion-bullet {
  width: 5px;
  height: 5px;
  background: var(--accent);
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 8px;
}

.typing {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: fit-content;
  border-top-left-radius: var(--radius-sm);
}

.typing-dots {
  display: flex;
  gap: 4px;
}

.typing-dots span {
  width: 5px;
  height: 5px;
  background: var(--accent);
  border-radius: 50%;
  animation: dotPulse 1.4s ease-in-out infinite;
}

.typing-dots span:nth-child(2) { animation-delay: 0.15s; }
.typing-dots span:nth-child(3) { animation-delay: 0.3s; }

@keyframes dotPulse {
  0%, 80%, 100% { transform: scale(0.5); opacity: 0.3; }
  40% { transform: scale(1); opacity: 1; }
}

.typing-label {
  font-size: 13px;
  color: var(--fg-3);
}

.msg-move,
.msg-enter-active,
.msg-leave-active {
  transition: all var(--dur-2) var(--ease);
}
.msg-enter-from,
.msg-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
.msg-leave-active {
  transition: opacity var(--dur-2) var(--ease);
}
</style>
