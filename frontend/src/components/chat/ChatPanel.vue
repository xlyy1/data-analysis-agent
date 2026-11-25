<template>
  <div ref="panelRef" class="chat-panel">
    <div v-if="loadingMessages" class="chat-messages">
      <div v-for="index in 3" :key="index" class="message assistant">
        <div class="msg-avatar"><div class="skeleton avatar-skeleton"></div></div>
        <div class="msg-body">
          <div class="skeleton" :style="{ height: index === 2 ? '52px' : '76px', width: index === 2 ? '62%' : '100%' }"></div>
        </div>
      </div>
    </div>

    <div v-else-if="!messages.length && !draft" class="chat-empty">
      <div class="empty-icon">
        <svg width="46" height="46" viewBox="0 0 48 48" fill="none">
          <rect x="6" y="6" width="16" height="16" rx="3" fill="currentColor" />
          <rect x="26" y="6" width="16" height="10" rx="3" fill="currentColor" opacity="0.4" />
          <rect x="6" y="26" width="16" height="10" rx="3" fill="currentColor" opacity="0.4" />
          <rect x="26" y="18" width="16" height="16" rx="3" fill="currentColor" opacity="0.7" />
        </svg>
      </div>
      <h1 class="empty-title">你好，我是 DataAgent</h1>
      <p class="empty-sub">用自然语言提问，我来生成只读 SQL、执行查询并发掘结论。你也可以先到「数据源」上传一份 Excel / CSV。</p>
      <div class="hint-grid">
        <button
          v-for="(hint, index) in hints"
          :key="hint"
          class="hint-card"
          type="button"
          :style="{ animationDelay: `${index * 60}ms` }"
          @click="$emit('send', hint)"
        >
          <span class="hint-label">{{ hint }}</span>
          <span class="hint-arrow">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </button>
      </div>
    </div>

    <div v-else class="chat-messages">
      <div v-for="message in messages" :key="message.id" class="message" :class="message.role">
        <div class="msg-avatar">
          <div v-if="message.role === 'user'" class="user-avatar">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <circle cx="7" cy="4.5" r="2.4" fill="currentColor" />
              <path d="M2.2 12.4c0-2.4 2-3.9 4.8-3.9s4.8 1.5 4.8 3.9" fill="currentColor" />
            </svg>
          </div>
          <div v-else class="ai-avatar">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <rect x="1" y="1" width="5" height="5" rx="1.2" fill="currentColor" />
              <rect x="8" y="1" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4" />
              <rect x="1" y="8" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4" />
              <rect x="8" y="6" width="5" height="5" rx="1.2" fill="currentColor" opacity="0.7" />
            </svg>
          </div>
        </div>

        <div class="msg-body">
          <div class="msg-content-wrap">
            <div v-if="message.role === 'user'" class="msg-content user">{{ message.content }}</div>
            <div
              v-else
              class="msg-content assistant markdown-content"
              v-html="renderMarkdown(message.content)"
            ></div>
          </div>

          <AnswerBlocks
            v-if="message.role === 'assistant'"
            :message="message"
            @send="$emit('send', $event)"
          />
        </div>
      </div>

      <div v-if="draft" class="message assistant">
        <div class="msg-avatar">
          <div class="ai-avatar pulse">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <rect x="1" y="1" width="5" height="5" rx="1.2" fill="currentColor" />
              <rect x="8" y="1" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4" />
              <rect x="1" y="8" width="5" height="3" rx="1.2" fill="currentColor" opacity="0.4" />
              <rect x="8" y="6" width="5" height="5" rx="1.2" fill="currentColor" opacity="0.7" />
            </svg>
          </div>
        </div>

        <div class="msg-body">
          <div v-if="isStreaming" class="progress-line">
            <span class="progress-dot"></span>
            <span class="progress-text">当前节点：{{ currentNode || '准备中' }}</span>
          </div>

          <div v-if="draft.content" class="msg-content-wrap">
            <div class="msg-content assistant markdown-content">
              <span v-html="renderMarkdown(draft.content)"></span>
              <span v-if="isStreaming" class="caret"></span>
            </div>
          </div>
          <div v-else-if="isStreaming" class="typing">
            <div class="typing-dots"><span></span><span></span><span></span></div>
            <span class="typing-label">正在分析数据…</span>
          </div>

          <AnswerBlocks :message="draft" @send="$emit('send', $event)" />
        </div>
      </div>

      <div class="chat-bottom-space"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import AnswerBlocks from './AnswerBlocks.vue'
import { renderMarkdown } from '../../lib/markdown'
import type { ChatMessage } from '../../api/types'

const props = defineProps<{
  messages: ChatMessage[]
  draft: ChatMessage | null
  isStreaming: boolean
  currentNode: string
  loadingMessages: boolean
}>()

defineEmits<{ send: [text: string] }>()

const panelRef = ref<HTMLElement | null>(null)

const hints = [
  '各城市的销售额排名是怎样的？',
  '哪个渠道的利润最低，为什么？',
  '帮我看看最近 30 天的销售趋势',
  '找出毛利率低于 15% 的产品类别',
]

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const element = panelRef.value
  if (element) element.scrollTop = element.scrollHeight
}

watch(
  () => [props.messages.length, props.draft?.content.length ?? 0, props.draft?.metadata],
  () => {
    void scrollToBottom()
  },
)

watch(
  () => props.isStreaming,
  (streaming) => {
    if (streaming) void scrollToBottom()
  },
)
</script>

<style scoped>
.chat-panel {
  flex: 1;
  overflow-y: auto;
  padding: 26px 48px 8px;
  min-height: 0;
}

.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  max-width: 580px;
  margin: 0 auto;
}

.empty-icon {
  color: var(--accent);
  margin-bottom: 26px;
  opacity: 0.85;
}

.empty-title {
  font-size: 27px;
  font-weight: 600;
  color: var(--fg-0);
  margin-bottom: 10px;
  letter-spacing: -0.03em;
}

.empty-sub {
  font-size: 13.5px;
  color: var(--fg-2);
  margin-bottom: 34px;
  line-height: 1.75;
  max-width: 440px;
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
  padding: 13px 15px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-1);
  color: var(--fg-1);
  font-size: 12.5px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
  text-align: left;
  animation: hintIn 500ms var(--ease-out) both;
}

.hint-label {
  flex: 1;
  text-align: left;
  line-height: 1.55;
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
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.chat-messages {
  max-width: 820px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
}

.chat-bottom-space {
  height: 12px;
}

.message {
  display: flex;
  gap: 13px;
  margin-bottom: 22px;
}

.msg-avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
}

.avatar-skeleton {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
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
  border: 1px solid var(--accent-line);
  color: var(--accent);
}

.ai-avatar.pulse {
  animation: aiPulse 1.5s ease-in-out infinite;
}

@keyframes aiPulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

.msg-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.msg-content-wrap {
  display: flex;
}

.message.user .msg-content-wrap {
  justify-content: flex-end;
}

.msg-content {
  border-radius: var(--radius);
  padding: 12px 16px;
  line-height: 1.7;
  font-size: 13.5px;
  max-width: 100%;
  min-width: 0;
}

.msg-content.assistant {
  background: var(--bg-1);
  border: 1px solid var(--border);
  color: var(--fg-1);
  border-top-left-radius: var(--radius-sm);
  width: 100%;
}

.msg-content.user {
  background: var(--accent);
  color: #ffffff;
  border-top-right-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 78%;
}

.caret {
  display: inline-block;
  width: 6px;
  height: 14px;
  margin-left: 2px;
  background: var(--accent);
  border-radius: 1px;
  vertical-align: text-bottom;
  animation: caretBlink 1s steps(2) infinite;
}

@keyframes caretBlink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.15;
  }
}

.progress-line {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  padding: 5px 11px;
  border-radius: 999px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  margin-bottom: 8px;
}

.progress-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: progressPulse 1.2s ease-in-out infinite;
}

.progress-text {
  font-size: 11.5px;
  color: var(--fg-2);
  font-family: var(--font-mono);
}

@keyframes progressPulse {
  0%,
  100% {
    opacity: 1;
    box-shadow: 0 0 0 0 var(--accent-glow);
  }
  50% {
    opacity: 0.5;
    box-shadow: 0 0 0 4px transparent;
  }
}

.typing {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 15px;
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

.typing-dots span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing-dots span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes dotPulse {
  0%,
  80%,
  100% {
    transform: scale(0.5);
    opacity: 0.3;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.typing-label {
  font-size: 12.5px;
  color: var(--fg-3);
}

@media (max-width: 1100px) {
  .chat-panel {
    padding: 22px 28px 8px;
  }
}
</style>
