/**
 * chatStore SSE state machine tests.
 * useSSE is mocked so we can drive events synchronously.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Capture the SSE handlers injected by chatStore so tests can fire them
let capturedOnEvent: ((e: unknown) => void) | null  = null
let capturedOnDone:  (() => void) | null             = null
let capturedOnError: ((e: Error) => void) | null     = null
let capturedCancel:  (() => void)                    = vi.fn()

vi.mock('@/composables/useSSE', () => ({
  useSSE: (_url: string, _payload: unknown, onEvent: unknown, onDone: unknown, onError: unknown) => {
    capturedOnEvent = onEvent as (e: unknown) => void
    capturedOnDone  = onDone as () => void
    capturedOnError = onError as (e: Error) => void
    return capturedCancel
  },
}))

import { useChatStore } from '@/stores/chatStore'

describe('useChatStore — SSE state machine', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    capturedOnEvent = null
    capturedOnDone  = null
    capturedOnError = null
    capturedCancel  = vi.fn()
  })

  it('sendQuery adds user + assistant messages', () => {
    const store = useChatStore()
    store.sendQuery('hello', {})
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0]!.role).toBe('user')
    expect(store.messages[0]!.content).toBe('hello')
    expect(store.messages[1]!.role).toBe('assistant')
    expect(store.messages[1]!.status).toBe('streaming')
    expect(store.isStreaming).toBe(true)
  })

  it('sendQuery is a no-op while already streaming', () => {
    const store = useChatStore()
    store.sendQuery('first', {})
    store.sendQuery('second', {})
    expect(store.messages).toHaveLength(2)
  })

  it('content event appends to assistant message', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnEvent!({ type: 'content', chunk: 'Hello ' })
    capturedOnEvent!({ type: 'content', chunk: 'world' })
    expect(store.messages[1]!.content).toBe('Hello world')
  })

  it('thinking event appends chunk to thinking.chunks', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnEvent!({ type: 'thinking', chunk: 'step 1' })
    capturedOnEvent!({ type: 'thinking', chunk: 'step 2' })
    expect(store.messages[1]!.thinking?.chunks).toEqual(['step 1', 'step 2'])
  })

  it('log_snippet event creates log artifact', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnEvent!({
      type: 'log_snippet',
      service: 'api',
      entries: [{ timestamp: 1, level: 'error', service: 'api', message: 'boom', labels: {} }],
    })
    const artifacts = store.messages[1]!.artifacts
    expect(artifacts).toHaveLength(1)
    expect(artifacts[0]!.kind).toBe('log')
  })

  it('metric event creates metric artifact', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnEvent!({
      type: 'metric',
      name: 'cpu',
      current: 72,
      threshold_warning: 70,
      threshold_critical: 90,
      unit: '%',
      series: [60, 65, 72],
      status: 'warn',
    })
    expect(store.messages[1]!.artifacts[0]!.kind).toBe('metric')
  })

  it('code_ref event creates code_ref artifact', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnEvent!({
      type: 'code_ref',
      file_path: 'src/main.py',
      line_start: 10,
      line_end: 20,
      snippet: 'def foo(): ...',
      relevance_score: 0.9,
    })
    expect(store.messages[1]!.artifacts[0]!.kind).toBe('code_ref')
  })

  it('done event marks message complete and clears streaming', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnEvent!({ type: 'content', chunk: 'answer' })
    capturedOnDone!()
    expect(store.messages[1]!.status).toBe('complete')
    expect(store.messages[1]!.thinking?.isDone).toBe(true)
    expect(store.isStreaming).toBe(false)
  })

  it('error event marks message error and sets store.error', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnError!(new Error('upstream 502'))
    expect(store.messages[1]!.status).toBe('error')
    expect(store.messages[1]!.errorMessage).toBe('upstream 502')
    expect(store.error).toBe('upstream 502')
    expect(store.isStreaming).toBe(false)
  })

  it('stopStream calls cancel and marks message complete', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    store.stopStream()
    expect(capturedCancel).toHaveBeenCalled()
    expect(store.isStreaming).toBe(false)
    expect(store.messages[1]!.status).toBe('complete')
  })

  it('clearMessages removes all messages', () => {
    const store = useChatStore()
    store.sendQuery('q', {})
    capturedOnDone!()
    store.clearMessages()
    expect(store.messages).toHaveLength(0)
  })

  it('retryLastQuery returns last user content and removes error msg', () => {
    const store = useChatStore()
    store.sendQuery('retry me', {})
    capturedOnError!(new Error('fail'))
    const content = store.retryLastQuery()
    expect(content).toBe('retry me')
    // error message removed
    expect(store.messages.at(-1)?.status).not.toBe('error')
  })
})
