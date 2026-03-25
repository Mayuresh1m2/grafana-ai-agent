import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useSSE } from '@/composables/useSSE'
import type { ChatMessage, SSEEvent } from '@/types/chat'

export const useReportStore = defineStore('report', () => {
  const content      = ref('')
  const isGenerating = ref(false)
  const isDone       = ref(false)
  const error        = ref<string | null>(null)

  let _cancel: (() => void) | null = null

  function generate(messages: ChatMessage[], context: Record<string, string>) {
    // Reset state
    content.value      = ''
    isDone.value       = false
    error.value        = null
    isGenerating.value = true

    const conversation = messages
      .filter((m) => m.status !== 'error' && m.content.trim())
      .map((m) => ({
        role:    m.role,
        content: m.role === 'assistant' ? m.content.slice(0, 3000) : m.content,
      }))

    _cancel = useSSE(
      '/api/v1/agent/report',
      { conversation, context },
      (event: SSEEvent) => {
        if (event.type === 'content') content.value += event.chunk
      },
      () => {
        isGenerating.value = false
        isDone.value       = true
        _cancel            = null
      },
      (err: Error) => {
        error.value        = err.message
        isGenerating.value = false
        _cancel            = null
      },
    )
  }

  function cancel() {
    _cancel?.()
    _cancel            = null
    isGenerating.value = false
  }

  function reset() {
    cancel()
    content.value = ''
    isDone.value  = false
    error.value   = null
  }

  return { content, isGenerating, isDone, error, generate, cancel, reset }
})
