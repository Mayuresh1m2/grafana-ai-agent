import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { agentApi } from '@/api'
import type { AgentQuery, ChatMessage } from '@/types/agent'
import type { ApiError } from '@/types/api'

export const useAgentStore = defineStore('agent', () => {
  // ── State ──────────────────────────────────────────────────────────────────
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const selectedModel = ref<string>('')

  // ── Getters ────────────────────────────────────────────────────────────────
  const hasMessages = computed(() => messages.value.length > 0)
  const lastMessage = computed<ChatMessage | null>(() =>
    messages.value.length > 0 ? (messages.value[messages.value.length - 1] ?? null) : null,
  )

  // ── Actions ────────────────────────────────────────────────────────────────
  function addMessage(role: ChatMessage['role'], content: string): ChatMessage {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role,
      content,
      timestamp: new Date(),
    }
    messages.value.push(msg)
    return msg
  }

  async function sendQuery(
    query: string,
    context?: Record<string, string>,
  ): Promise<void> {
    const trimmed = query.trim()
    if (!trimmed) return

    error.value = null
    isLoading.value = true
    addMessage('user', trimmed)

    const payload: AgentQuery = {
      query: trimmed,
      context,
      model: selectedModel.value,
    }

    try {
      const response = await agentApi.query(payload)
      addMessage('assistant', response.answer)
    } catch (err) {
      const apiErr = err as ApiError
      error.value = apiErr.detail ?? 'An unexpected error occurred.'
    } finally {
      isLoading.value = false
    }
  }

  function clearMessages(): void {
    messages.value = []
    error.value = null
  }

  function setModel(model: string): void {
    selectedModel.value = model
  }

  return {
    // state
    messages,
    isLoading,
    error,
    selectedModel,
    // getters
    hasMessages,
    lastMessage,
    // actions
    addMessage,
    sendQuery,
    clearMessages,
    setModel,
  }
})
