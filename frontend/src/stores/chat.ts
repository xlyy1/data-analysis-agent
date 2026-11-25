import { ref } from 'vue'
import { defineStore } from 'pinia'

import { ApiError, conversationApi, streamChat, toApiError } from '../api/client'
import type { ChatMessage, ConversationSummary, StreamEvent } from '../api/types'

const NODE_LABELS: Record<string, string> = {
  understand_intent: '理解问题',
  generate_query: '生成 SQL',
  execute_query: '执行查询',
  analyze_results: '分析结果',
  diagnose: '诊断原因',
  generate_visualization: '生成图表',
  format_response: '整理回答',
  retry: '修正 SQL 后重试',
}

export function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? node
}

/**
 * 对话状态：会话列表 + 当前会话消息 + SSE 流式草稿。
 * 草稿（draft）在流式过程中实时更新，结束后才并入 messages，
 * 这样"正在输出的回答"和"历史消息"的渲染可以分开处理。
 */
export const useChatStore = defineStore('chat', () => {
  const conversations = ref<ConversationSummary[]>([])
  const currentConvId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const draft = ref<ChatMessage | null>(null)
  const isStreaming = ref(false)
  const currentNode = ref('')
  const error = ref<ApiError | null>(null)
  const loadingConversations = ref(false)
  const loadingMessages = ref(false)

  let abortController: AbortController | null = null

  async function fetchConversations(): Promise<void> {
    loadingConversations.value = true
    try {
      conversations.value = await conversationApi.list()
    } catch (caught) {
      error.value = toApiError(caught)
    } finally {
      loadingConversations.value = false
    }
  }

  async function createConversation(): Promise<string> {
    const conversation = await conversationApi.create()
    conversations.value = [conversation, ...conversations.value]
    currentConvId.value = conversation.id
    messages.value = []
    error.value = null
    return conversation.id
  }

  async function ensureConversation(): Promise<string> {
    if (currentConvId.value) return currentConvId.value
    return createConversation()
  }

  async function deleteConversation(id: string): Promise<void> {
    try {
      await conversationApi.remove(id)
      conversations.value = conversations.value.filter((item) => item.id !== id)
      if (currentConvId.value === id) {
        currentConvId.value = null
        messages.value = []
      }
    } catch (caught) {
      error.value = toApiError(caught)
    }
  }

  async function selectConversation(id: string): Promise<void> {
    if (isStreaming.value || id === currentConvId.value) return
    currentConvId.value = id
    loadingMessages.value = true
    error.value = null
    try {
      messages.value = await conversationApi.messages(id)
    } catch (caught) {
      messages.value = []
      error.value = toApiError(caught)
    } finally {
      loadingMessages.value = false
    }
  }

  function startNewChat(): void {
    if (isStreaming.value) return
    currentConvId.value = null
    messages.value = []
    draft.value = null
    error.value = null
    currentNode.value = ''
  }

  function stopStreaming(): void {
    abortController?.abort()
  }

  function applyEvent(target: ChatMessage, event: StreamEvent): void {
    switch (event.type) {
      case 'node':
        currentNode.value = event.error
          ? `${nodeLabel(event.node)}（${event.error}）`
          : nodeLabel(event.node)
        break
      case 'text':
        target.content += event.content
        break
      case 'metadata':
        target.metadata = event.content
        break
      case 'clarification':
        target.content = event.content || target.content
        target.options = event.options ?? []
        break
      case 'confirm_sql':
        target.content = `⚠️ 检测到非只读操作，已拒绝执行：\n\n\`\`\`sql\n${event.sql}\n\`\`\`\n\n本系统只执行只读查询。`
        target.metadata = { sql: event.sql }
        break
      case 'error':
        error.value = new ApiError(event.content || '分析过程出错，请重试', {
          code: 'stream_error',
          requestId: event.request_id ?? '',
          details: event.detail ?? '',
        })
        if (!target.content) target.content = event.content
        break
      default:
        break
    }
  }

  async function sendMessage(rawText: string): Promise<void> {
    const content = rawText.trim()
    if (!content || isStreaming.value) return

    error.value = null
    let conversationId: string
    try {
      conversationId = await ensureConversation()
    } catch (caught) {
      error.value = toApiError(caught)
      return
    }

    messages.value.push({
      id: `local-${Date.now()}`,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    })

    const assistant: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
    }
    draft.value = assistant
    isStreaming.value = true
    currentNode.value = '准备中'

    const controller = new AbortController()
    abortController = controller

    try {
      await streamChat(
        { conversation_id: conversationId, message: content },
        (event) => applyEvent(assistant, event),
        controller.signal,
      )
    } catch (caught) {
      if (!controller.signal.aborted) error.value = toApiError(caught)
    } finally {
      const aborted = controller.signal.aborted
      isStreaming.value = false
      currentNode.value = ''
      abortController = null

      const finished = draft.value
      draft.value = null
      if (finished) {
        const hasContent = finished.content.trim().length > 0
        if (hasContent) {
          messages.value.push({ ...finished, content: aborted ? `${finished.content}\n\n（已手动停止）` : finished.content })
        } else if (!error.value) {
          messages.value.push({ ...finished, content: aborted ? '已停止生成。' : '没有收到回答，请重试或换个问法。' })
        }
      }

      // 首轮问答后后端会把标题从「新对话」改成问题摘要
      void fetchConversations()
    }
  }

  function clearError(): void {
    error.value = null
  }

  return {
    conversations,
    currentConvId,
    messages,
    draft,
    isStreaming,
    currentNode,
    error,
    loadingConversations,
    loadingMessages,
    fetchConversations,
    createConversation,
    deleteConversation,
    selectConversation,
    startNewChat,
    sendMessage,
    stopStreaming,
    clearError,
  }
})
