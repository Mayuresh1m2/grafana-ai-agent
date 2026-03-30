import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSSE } from '@/composables/useSSE'
import type { ChatMessage, SSEEvent, Artifact } from '@/types/chat'

let _msgCounter = 0
function newId() { return `msg_${++_msgCounter}_${Date.now()}` }

export const useChatStore = defineStore('chat', () => {
  // ── State ────────────────────────────────────────────────────────────────
  const messages       = ref<ChatMessage[]>([])
  const isStreaming    = ref(false)
  const error          = ref<string | null>(null)
  const sessionExpired = ref(false)
  let   _cancelSSE: (() => void) | null = null

  // ── Computed ─────────────────────────────────────────────────────────────
  const lastMessage  = computed(() => messages.value.at(-1) ?? null)
  const hasMessages  = computed(() => messages.value.length > 0)

  // ── Actions ──────────────────────────────────────────────────────────────
  function sendQuery(query: string, sessionPayload: Record<string, unknown>) {
    if (isStreaming.value) return

    // Add user message
    messages.value.push({
      id:          newId(),
      role:        'user',
      content:     query,
      thinking:    null,
      artifacts:   [],
      suggestions: [],
      timestamp:   new Date(),
      status:      'complete',
    })

    // Add empty assistant message (will be filled by SSE)
    const assistantMsg: ChatMessage = {
      id:          newId(),
      role:        'assistant',
      content:     '',
      thinking:    { chunks: [], isDone: false, collapsed: false },
      artifacts:   [],
      suggestions: [],
      timestamp:   new Date(),
      status:      'streaming',
    }
    messages.value.push(assistantMsg)
    isStreaming.value = true
    error.value       = null

    const msgIndex = messages.value.length - 1

    _cancelSSE = useSSE(
      '/api/v1/agent/query',
      { query, ...sessionPayload },
      (event: SSEEvent) => _handleEvent(event, msgIndex),
      ()                => _handleDone(msgIndex),
      (err: Error)      => _handleError(err, msgIndex),
    )
  }

  function stopStream() {
    if (_cancelSSE) {
      _cancelSSE()
      _cancelSSE = null
    }
    const idx = messages.value.findIndex((m) => m.status === 'streaming')
    if (idx !== -1) {
      const msg = messages.value[idx]
      if (msg.thinking) msg.thinking.isDone = true
      messages.value[idx] = { ...msg, status: 'complete' }
    }
    isStreaming.value = false
  }

  function retryLastQuery(): string | undefined {
    // Find the last user message before popping anything
    const lastUserIdx = messages.value.findLastIndex((m) => m.role === 'user')
    if (lastUserIdx === -1) return undefined
    const query = messages.value[lastUserIdx]!.content

    // Remove the error assistant message, then the user message — sendQuery will re-add both
    if (messages.value.at(-1)?.status === 'error') messages.value.pop()
    messages.value.splice(lastUserIdx, 1)
    return query
  }

  function clearMessages() {
    stopStream()
    messages.value = []
    error.value    = null
  }

  // ── Private SSE handlers ─────────────────────────────────────────────────
  function _handleEvent(event: SSEEvent, idx: number) {
    const msg = messages.value[idx]
    if (!msg) return

    if (event.type === 'thinking') {
      if (msg.thinking) msg.thinking.chunks.push(event.chunk)
      return
    }
    if (event.type === 'content') {
      msg.content += event.chunk
      return
    }
    if (event.type === 'log_snippet') {
      const artifact: Artifact = { kind: 'log', service: event.service, entries: event.entries }
      msg.artifacts = [...msg.artifacts, artifact]
      return
    }
    if (event.type === 'metric') {
      const artifact: Artifact = {
        kind: 'metric',
        name:               event.name,
        current:            event.current,
        threshold_warning:  event.threshold_warning,
        threshold_critical: event.threshold_critical,
        unit:               event.unit,
        series:             event.series,
        status:             event.status,
      }
      msg.artifacts = [...msg.artifacts, artifact]
      return
    }
    if (event.type === 'code_ref') {
      const artifact: Artifact = {
        kind:            'code_ref',
        file_path:       event.file_path,
        line_start:      event.line_start,
        line_end:        event.line_end,
        snippet:         event.snippet,
        relevance_score: event.relevance_score,
        repo_path:       event.repo_path,
      }
      msg.artifacts = [...msg.artifacts, artifact]
      return
    }
    if (event.type === 'suggestions') {
      msg.suggestions = event.items
      return
    }
    if (event.type === 'error') {
      if (msg.thinking) msg.thinking.isDone = true
      messages.value[idx] = { ...msg, status: 'error', errorMessage: (event as { type: string; message?: string }).message }
      isStreaming.value    = false
      _cancelSSE           = null
      if ((event as { type: string; code?: string }).code === 'session_expired') {
        sessionExpired.value = true
      }
    }
  }

  function _handleDone(idx: number) {
    const msg = messages.value[idx]
    if (msg) {
      if (msg.thinking) msg.thinking.isDone = true
      messages.value[idx] = { ...msg, status: 'complete' }
    }
    isStreaming.value = false
    _cancelSSE = null
  }

  function _handleError(err: Error, idx: number) {
    const msg = messages.value[idx]
    if (msg) {
      if (msg.thinking) msg.thinking.isDone = true
      messages.value[idx] = { ...msg, status: 'error', errorMessage: err.message }
    }
    error.value       = err.message
    isStreaming.value = false
    _cancelSSE        = null
    if ((err as Error & { code?: string }).code === 'session_expired') {
      sessionExpired.value = true
    }
  }

  return {
    messages, isStreaming, error, sessionExpired, lastMessage, hasMessages,
    sendQuery, stopStream, retryLastQuery, clearMessages,
  }
})
