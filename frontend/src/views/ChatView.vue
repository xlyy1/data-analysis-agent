<template>
  <div class="chat-view">
    <aside class="conv-list" :class="{ collapsed: collapsed }">
      <div class="conv-header">
        <button class="new-chat" type="button" :disabled="chat.isStreaming" @click="newChat">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 2.5v11M2.5 8h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
          <span v-show="!collapsed">新对话</span>
        </button>
      </div>

      <div class="conv-scroll">
        <div v-if="chat.loadingConversations" class="conv-loading">
          <div v-for="index in 5" :key="index" class="skeleton conv-skeleton"></div>
        </div>

        <template v-else>
          <div class="conv-list-inner">
            <div
              v-for="conv in chat.conversations"
              :key="conv.id"
              class="conv-item"
              :class="{ active: conv.id === chat.currentConvId }"
            >
              <button
                class="conv-main"
                type="button"
                :title="conv.title || '新对话'"
                @click="selectConversation(conv.id)"
              >
                <span class="conv-icon">
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                    <path d="M12 3.5a2 2 0 00-2-2H4a2 2 0 00-2 2v5a2 2 0 002 2h2.5l2 2v-2H10a2 2 0 002-2v-5z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round" />
                  </svg>
                </span>
                <span v-show="!collapsed" class="conv-meta">
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                  <span class="conv-time">{{ formatRelative(conv.updated_at || conv.created_at) }}</span>
                </span>
              </button>

              <div v-show="!collapsed" class="conv-del-wrap">
                <template v-if="pendingDeleteId === conv.id">
                  <button class="conv-confirm" type="button" @click="confirmDelete(conv.id)">删除</button>
                  <button class="conv-cancel" type="button" @click="pendingDeleteId = null">取消</button>
                </template>
                <button
                  v-else
                  class="conv-del"
                  type="button"
                  title="删除对话"
                  @click="askDelete(conv.id)"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                    <path d="M2 3h8M4 3V2h4v1M3 3l.4 7a1 1 0 001 .9h3.2a1 1 0 001-.9L9 3" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <div v-if="!chat.conversations.length" class="conv-empty">
            <span>暂无对话记录</span>
          </div>
        </template>
      </div>

      <div class="conv-footer">
        <button class="toggle" type="button" :title="collapsed ? '展开列表' : '收起列表'" @click="collapsed = !collapsed">
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            :style="{ transform: collapsed ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }"
          >
            <path d="M9.5 2.5l-5 4.5 5 4.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </aside>

    <div class="chat-main">
      <ChatPanel
        :messages="chat.messages"
        :draft="chat.draft"
        :is-streaming="chat.isStreaming"
        :current-node="chat.currentNode"
        :loading-messages="chat.loadingMessages"
        @send="handleSend"
      />

      <div class="chat-input-bar">
        <ErrorAlert
          v-if="chat.error"
          class="input-error"
          :error="chat.error"
          title="对话出错"
          @dismiss="chat.clearError()"
        />

        <div class="input-shell" :class="{ focused: inputFocused }">
          <textarea
            ref="inputRef"
            v-model="inputText"
            class="chat-input"
            rows="1"
            :placeholder="chat.isStreaming ? '正在生成回答…' : '向 DataAgent 提问关于你的数据…'"
            :disabled="chat.isStreaming"
            @keydown="onKeydown"
            @input="autoResize"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
          ></textarea>

          <button
            v-if="chat.isStreaming"
            class="stop"
            type="button"
            title="停止生成"
            @click="chat.stopStreaming()"
          >
            停止
          </button>
          <button
            v-else
            class="send"
            type="button"
            :disabled="!inputText.trim()"
            title="发送"
            @click="handleSend(inputText)"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M1.5 7l13-5-5 13-3-4-5-4z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" fill="currentColor" fill-opacity="0.2" />
            </svg>
          </button>
        </div>

        <div class="input-hint">
          <kbd>Enter</kbd> 发送
          <span class="sep">·</span>
          <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

import ChatPanel from '../components/chat/ChatPanel.vue'
import ErrorAlert from '../components/ui/ErrorAlert.vue'
import { useChatStore } from '../stores/chat'

const chat = useChatStore()

const inputText = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const collapsed = ref(false)
const inputFocused = ref(false)
const pendingDeleteId = ref<string | null>(null)

onMounted(async () => {
  await chat.fetchConversations()
  if (!chat.currentConvId && chat.conversations.length) {
    await chat.selectConversation(chat.conversations[0].id)
  }
})

async function newChat(): Promise<void> {
  chat.startNewChat()
  await nextTick()
  inputRef.value?.focus()
}

function selectConversation(id: string): void {
  pendingDeleteId.value = null
  void chat.selectConversation(id)
}

function askDelete(id: string): void {
  pendingDeleteId.value = id
  window.setTimeout(() => {
    if (pendingDeleteId.value === id) pendingDeleteId.value = null
  }, 4000)
}

async function confirmDelete(id: string): Promise<void> {
  pendingDeleteId.value = null
  await chat.deleteConversation(id)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    handleSend(inputText.value)
  }
}

function autoResize(): void {
  const element = inputRef.value
  if (!element) return
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 160)}px`
}

function handleSend(text: string): void {
  if (!text.trim() || chat.isStreaming) return
  inputText.value = ''
  void nextTick(() => autoResize())
  void chat.sendMessage(text)
}

function formatRelative(iso: string): string {
  if (!iso) return ''
  const normalized = iso.includes('T') && !/[Z+-]\d/.test(iso.slice(10)) ? `${iso}Z` : iso
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return ''
  const diff = Date.now() - date.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return `${date.getMonth() + 1}月${date.getDate()}日`
}
</script>

<style scoped>
.chat-view {
  display: flex;
  height: 100vh;
}

.conv-list {
  width: 244px;
  min-width: 244px;
  background: var(--bg-1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width var(--dur-3) var(--ease-out), min-width var(--dur-3) var(--ease-out);
}

.conv-list.collapsed {
  width: 56px;
  min-width: 56px;
}

.conv-header {
  padding: 12px;
  border-bottom: 1px solid var(--border);
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  width: 100%;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-2);
  color: var(--fg-1);
  font-size: 12.5px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
}

.new-chat:hover:not(:disabled) {
  background: var(--accent-hi);
  border-color: var(--accent-line);
  color: var(--accent);
}

.new-chat:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.conv-list.collapsed .new-chat {
  padding: 0;
}

.conv-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px;
  min-height: 0;
}

.conv-loading {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px;
}

.conv-skeleton {
  height: 42px;
}

.conv-list-inner {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.conv-item {
  display: flex;
  align-items: stretch;
  border-radius: var(--radius-sm);
  color: var(--fg-3);
  position: relative;
  transition: background var(--dur-1) var(--ease-out);
}

.conv-item:hover {
  background: var(--bg-3);
}

.conv-item.active {
  background: var(--bg-3);
  color: var(--fg-0);
}

.conv-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: 1px;
  background: var(--accent);
}

.conv-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 9px;
  border: none;
  background: transparent;
  color: inherit;
  font-family: inherit;
  cursor: pointer;
  min-width: 0;
  text-align: left;
}

.conv-list.collapsed .conv-main {
  justify-content: center;
  padding: 8px 0;
}

.conv-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--bg-2);
  color: var(--fg-3);
  flex-shrink: 0;
}

.conv-item.active .conv-icon {
  background: var(--accent-hi);
  color: var(--accent);
}

.conv-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.conv-title {
  font-size: 12.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-time {
  font-size: 10.5px;
  color: var(--fg-4);
  font-family: var(--font-mono);
}

.conv-del-wrap {
  display: flex;
  align-items: center;
  gap: 2px;
  padding-right: 4px;
}

.conv-del {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--fg-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  opacity: 0;
  transition: all var(--dur-1) var(--ease-out);
}

.conv-item:hover .conv-del {
  opacity: 1;
}

.conv-del:hover {
  background: rgba(248, 113, 113, 0.12);
  color: var(--danger);
}

.conv-confirm,
.conv-cancel {
  border: none;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-family: var(--font-sans);
  padding: 3px 6px;
  cursor: pointer;
}

.conv-confirm {
  background: rgba(248, 113, 113, 0.18);
  color: var(--danger);
}

.conv-cancel {
  background: var(--bg-4);
  color: var(--fg-2);
}

.conv-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 36px 16px;
  color: var(--fg-4);
  font-size: 11.5px;
  text-align: center;
}

.conv-footer {
  padding: 8px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: center;
}

.toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: var(--fg-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}

.toggle:hover {
  background: var(--bg-3);
  color: var(--fg-1);
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-0);
  min-width: 0;
}

.chat-input-bar {
  padding: 10px 48px 24px;
  background: linear-gradient(180deg, transparent, var(--bg-0) 24%);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.input-error {
  max-width: 820px;
  width: 100%;
  margin: 0 auto;
}

.input-shell {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 7px 7px 7px 15px;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: all var(--dur-2) var(--ease-out);
  max-width: 820px;
  width: 100%;
  margin: 0 auto;
}

.input-shell.focused {
  border-color: var(--border-accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

.chat-input {
  flex: 1;
  resize: none;
  padding: 8px 0;
  background: transparent;
  border: none;
  color: var(--fg-0);
  font-family: var(--font-sans);
  font-size: 13.5px;
  line-height: 1.6;
  outline: none;
  max-height: 160px;
}

.chat-input::placeholder {
  color: var(--fg-3);
}

.chat-input:disabled {
  cursor: not-allowed;
}

.send {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #ffffff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--dur-2) var(--ease-out);
}

.send:hover:not(:disabled) {
  background: var(--accent-dim);
}

.send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.stop {
  flex-shrink: 0;
  height: 34px;
  padding: 0 13px;
  border: 1px solid rgba(248, 113, 113, 0.3);
  border-radius: var(--radius-sm);
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger);
  font-size: 12px;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--dur-1) var(--ease-out);
}

.stop:hover {
  background: rgba(248, 113, 113, 0.18);
}

.input-hint {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: var(--fg-4);
}

.input-hint .sep {
  color: var(--fg-4);
}

.input-hint kbd {
  display: inline-block;
  padding: 1px 5px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--fg-3);
  line-height: 1.4;
}

@media (max-width: 1100px) {
  .conv-list {
    width: 208px;
    min-width: 208px;
  }
  .chat-input-bar {
    padding: 8px 24px 18px;
  }
}
</style>
