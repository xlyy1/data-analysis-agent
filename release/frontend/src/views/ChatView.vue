<template>
  <div class="chat-view">
    <!-- Conversation List Sidebar -->
    <aside class="conv-sidebar" :class="{ collapsed: convCollapsed }">
      <div class="conv-header">
        <t-button theme="primary" block @click="newChat">
          <t-icon name="add" /> <span v-show="!convCollapsed">新对话</span>
        </t-button>
      </div>
      <div class="conv-list">
        <div
          v-for="conv in chat.conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === chat.currentConvId }"
        >
          <div class="conv-info" @click="chat.selectConversation(conv.id)">
            <t-icon name="chat" size="14px" />
            <span class="conv-title">{{ conv.title || '新对话' }}</span>
            <span class="conv-date">{{ formatDate(conv.updated_at) }}</span>
          </div>
          <t-popconfirm content="确定删除此对话？" @confirm="handleDelete(conv.id)">
            <t-button variant="text" size="small" shape="square" class="conv-del-btn">
              <t-icon name="delete" size="14px" />
            </t-button>
          </t-popconfirm>
        </div>
      </div>
      <div class="conv-footer">
        <t-button variant="text" size="small" @click="convCollapsed = !convCollapsed" class="toggle-btn">
          <t-icon :name="convCollapsed ? 'chevron-right' : 'chevron-left'" />
        </t-button>
      </div>
    </aside>

    <!-- Main Chat Area -->
    <div class="chat-main">
      <ChatPanel
        :messages="chat.messages"
        :is-streaming="chat.isStreaming"
        @send="handleSend"
      />
      <div class="chat-input-bar">
        <div class="input-wrapper">
          <textarea
            ref="inputRef"
            v-model="inputText"
            class="chat-input"
            placeholder="输入你的数据分析问题... (Enter 发送, Shift+Enter 换行)"
            rows="1"
            @keydown="onKeydown"
            @input="autoResize"
          ></textarea>
          <t-button
            theme="primary"
            :disabled="!inputText.trim() || chat.isStreaming"
            @click="handleSend(inputText)"
            class="send-btn"
          >
            <t-icon name="send" />
          </t-button>
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
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function handleSend(text: string) {
  if (!text?.trim() || chat.isStreaming) return
  inputText.value = ''
  nextTick(() => autoResize())
  chat.sendMessage(text.trim())
}

function formatDate(iso: string): string {
  if (!iso) return ''
  // Append Z if no timezone info so JS treats it as UTC
  const d = new Date(iso.includes('T') && !iso.match(/[Z+-]\d/) ? iso + 'Z' : iso)
  const now = new Date()
  // Handle timezone offset: treat the ISO string as UTC
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

/* Conversation Sidebar */
.conv-sidebar {
  width: 260px;
  min-width: 260px;
  background: var(--bg-primary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
}

.conv-sidebar.collapsed {
  width: 50px;
  min-width: 50px;
}

.conv-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}

.conv-sidebar.collapsed .conv-header {
  padding: 12px 6px;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: var(--radius);
  transition: all 0.15s;
  color: var(--text-secondary);
}

.conv-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.conv-item.active {
  background: var(--bg-surface);
  color: var(--accent);
}

.conv-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  cursor: pointer;
  min-width: 0;
}

.conv-sidebar.collapsed .conv-info {
  display: none;
}

.conv-title {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-date {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.conv-del-btn {
  color: var(--text-muted) !important;
  opacity: 0;
  transition: opacity 0.15s;
  flex-shrink: 0;
}

.conv-item:hover .conv-del-btn {
  opacity: 1;
}

.conv-del-btn:hover {
  color: var(--danger) !important;
}

.conv-footer {
  padding: 8px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: center;
}

.toggle-btn {
  color: var(--text-muted) !important;
  min-width: unset;
}

.toggle-btn:hover {
  color: var(--text-primary) !important;
}

/* Chat Main */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.chat-input-bar {
  padding: 12px 24px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-primary);
}

.input-wrapper {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
  resize: none;
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.2s;
}

.chat-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-glow);
}

.chat-input::placeholder {
  color: var(--text-muted);
}

.send-btn {
  flex-shrink: 0;
}

/* Scrollbar */
.conv-list::-webkit-scrollbar {
  width: 4px;
}
.conv-list::-webkit-scrollbar-track {
  background: transparent;
}
.conv-list::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 2px;
}
</style>
