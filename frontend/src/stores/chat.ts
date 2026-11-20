import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  metadata?: {
    sql?: string
    sql_explanation?: string
    analysis_type?: string
    chart_config?: { chart_type: string; title: string; echarts_option: any }
    diagnosis_causes?: string[]
    diagnosis_suggestions?: string[]
  }
  created_at: string
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConvId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)

  async function fetchConversations() {
    const res = await api.get('/conversations/')
    conversations.value = res.data
  }

  async function createConversation() {
    const res = await api.post('/conversations/')
    conversations.value.unshift(res.data)
    return res.data.id
  }

  async function deleteConversation(convId: string) {
    await api.delete(`/conversations/${convId}`)
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (currentConvId.value === convId) {
      currentConvId.value = null
      messages.value = []
    }
  }

  async function selectConversation(id: string) {
    currentConvId.value = id
    const res = await api.get(`/conversations/${id}/messages`)
    messages.value = res.data
  }

  async function sendMessage(text: string) {
    if (!currentConvId.value) {
      const id = await createConversation()
      currentConvId.value = id
      // Set title from first message
      const idx = conversations.value.findIndex(c => c.id === id)
      if (idx >= 0) conversations.value[idx].title = text.slice(0, 30)
    }

    messages.value.push({
      id: 'temp-' + Date.now(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    })

    isStreaming.value = true

    try {
      const res = await api.post('/conversations/chat', {
        conversation_id: currentConvId.value,
        message: text,
      })

      const data = res.data

      // Update conversation title from first exchange
      const cidx = conversations.value.findIndex(c => c.id === currentConvId.value)
      if (cidx >= 0 && conversations.value[cidx].title === '新对话' && !data.needs_clarification) {
        conversations.value[cidx].title = text.slice(0, 30)
      }

      if (data.needs_clarification) {
        messages.value.push({
          id: data.message_id,
          role: 'assistant',
          content: data.content,
          created_at: new Date().toISOString(),
          metadata: {
            diagnosis_causes: data.clarification_options,
          },
        })
      } else {
        messages.value.push({
          id: data.message_id,
          role: 'assistant',
          content: data.content,
          metadata: data.metadata,
          created_at: new Date().toISOString(),
        })
      }
    } catch (e: any) {
      messages.value.push({
        id: 'err-' + Date.now(),
        role: 'assistant',
        content: `抱歉，请求出错：${e.message}`,
        created_at: new Date().toISOString(),
      })
    } finally {
      isStreaming.value = false
    }
  }

  return {
    conversations,
    currentConvId,
    messages,
    isStreaming,
    fetchConversations,
    createConversation,
    deleteConversation,
    selectConversation,
    sendMessage,
  }
})
