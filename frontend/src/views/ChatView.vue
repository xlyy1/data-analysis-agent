<template>
  <div class="chat-view">
    <aside class="conv-list" :class="{ collapsed: convCollapsed }">
      <div class="conv-header">
        <button class="new-chat" @click="newChat">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 2.5v11M2.5 8h11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <transition name="fade">
            <span v-show="!convCollapsed">新对话</span>
          </transition>
        </button>
      </div>
      <div class="conv-scroll">
        <transition-group name="list" tag="div" class="conv-list-inner">
          <div
            v-for="conv in chat.conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: conv.id === chat.currentConvId }"
          >
            <div class="conv-main" @click="chat.selectConversation(conv.id)">
              <div class="conv-icon">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M12 3.5a2 2 0 00-2-2H4a2 2 0 00-2 2v5a2 2 0 002 2h2.5l2 2v-2H10a2 2 0 002-2v-5z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>
                </svg>
              </div>
              <transition name="fade">
                <div v-show="!convCollapsed" class="conv-meta">
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                  <span class="conv-time">{{ formatDate(conv.updated_at) }}</span>
                </div>
              </transition>
            </div>
            <transition name="fade">
              <button v-show="!convCollapsed" class="conv-del" @click="handleDelete(conv.id)">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M2 3h8M4 3V2h4v1M3 3l.4 7a1 1 0 001 .9h3.2a1 1 0 001-.9L9 3" stroke="currentColor" stroke-width="1" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
            </transition>
          </div>
        </transition-group>
        <div v-if="chat.conversations.length === 0" class="conv-empty">
          <span>暂无对话记录</span>
        </div>
      </div>
      <div class="conv-footer">
        <button class="toggle" @click="convCollapsed = !convCollapsed">
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            :style="{ transform: convCollapsed ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }"
          >
            <path d="M9.5 2.5l-5 4.5 5 4.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </aside>

    <div class="chat-main">
      <ChatPanel
        :messages="chat.messages"
        :is-streaming="chat.isStreaming"
        @send="handleSend"
      />
      <div class="chat-input-bar">
        <div class="input-shell" :class="{ focused: inputFocused }">
          <textarea
            ref="inputRef"
            v-model="inputText"
            class="chat-input"
            placeholder="向 DataAgent 提问关于你的数据..."
            rows="1"
            @keydown="onKeydown"
            @input="autoResize"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
          ></textarea>
          <button
            class="send"
            :disabled="!inputText.trim() || chat.isStreaming"
            @click="handleSend(inputText)"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M1.5 7l13-5-5 13-3-4-5-4z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" fill="currentColor" fill-opacity="0.2"/>
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
import { ref, onMounted, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import ChatPanel from '../components/chat/ChatPanel.vue'

const chat = useChatStore()
const inputText = ref('')
const inputRef = ref<HTMLTextAreaElement>()
const convCollapsed = ref(false)
const inputFocused = ref(false)

onMounted(() => {
  chat.fetchConversations()
})

async function newChat() {
  await chat.createConversation()
  chat.messages = []
  chat.currentConvId = chat.conversations[0]?.id
  nextTick(() => inputRef.value?.focus())
}

async function handleDelete(convId: string) {
  await chat.deleteConversation(convId)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend(inputText.value)
  }
}

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function handleSend(text: string) {
  if (!text?.trim() || chat.isStreaming) return
  inputText.value = ''
  nextTick(() => autoResize())
  chat.sendMessage(text.trim())
}

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso.includes('T') && !iso.match(/[Z+-]\d/) ? iso + 'Z' : iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`
  const month = d.getMonth() + 1
  const day = d.getDate()
  return `${month}月${day}日`
}
</script>

<style scoped>
.chat-view {
  display: flex;
  height: 100vh;
}

.conv-list {
  width: 260px;
  min-width: 260px;
  background: var(--bg-1);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width var(--dur-3) var(--ease-out), min-width var(--dur-3) var(--ease-out);
}

.conv-list.collapsed {
  width: 52px;
  min-width: 52px;
}

.conv-header {
  padding: 14px 12px;
  border-bottom: 1px solid var(--border);
}

.new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-3);
  color: var(--fg-1);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-2) var(--ease-out);
  font-family: var(--font-sans);
}

.new-chat:hover {
  background: var(--accent-hi);
  border-color: var(--accent-line);
  color: var(--accent);
}

.conv-list.collapsed .new-chat {
  padding: 0;
}

.conv-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px;
}

.conv-scroll::-webkit-scrollbar {
  width: 4px;
}
.conv-scroll::-webkit-scrollbar-thumb {
  background: var(--bg-4);
  border-radius: 2px;
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
  transition: all var(--dur-1) var(--ease-out);
  color: var(--fg-3);
  position: relative;
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
  gap: 10px;
  padding: 9px 10px;
  cursor: pointer;
  min-width: 0;
}

.conv-list.collapsed .conv-main {
  justify-content: center;
  padding: 9px 0;
}

.conv-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--bg-3);
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
  gap: 2px;
  min-width: 0;
}

.conv-title {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: inherit;
}

.conv-time {
  font-size: 11px;
  color: var(--fg-3);
  font-family: var(--font-mono);
}

.conv-del {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: auto;
  margin-right: 4px;
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
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger);
}

.conv-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--fg-3);
  font-size: 12px;
}

.conv-footer {
  padding: 10px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: center;
}

.toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
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
  padding: 16px 48px 28px;
  background: var(--bg-0);
}

.input-shell {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 8px 8px 16px;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: all var(--dur-2) var(--ease-out);
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
  font-size: 14px;
  line-height: 1.6;
  outline: none;
  max-height: 160px;
}

.chat-input::placeholder {
  color: var(--fg-3);
}

.send {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
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

.send:active:not(:disabled) {
  transform: scale(0.97);
}

.send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.input-hint {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--fg-3);
}

.input-hint .sep {
  color: var(--fg-4);
}

.input-hint kbd {
  display: inline-block;
  padding: 1px 5px;
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--fg-2);
  line-height: 1;
}

.list-move,
.list-enter-active,
.list-leave-active {
  transition: all var(--dur-2) var(--ease);
}
.list-enter-from,
.list-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}
.list-move {
  transition: transform var(--dur-2) var(--ease);
}
</style>
