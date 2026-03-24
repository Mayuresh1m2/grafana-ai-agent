import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '@/stores/agent'
import type { AgentResponse } from '@/types/agent'

// Mock the api module
vi.mock('@/api', () => ({
  agentApi: {
    query: vi.fn(),
    health: vi.fn(),
  },
}))

import { agentApi } from '@/api'

describe('useAgentStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('smoke: store module imports correctly', () => {
    const { useAgentStore: s } = await import('@/stores/agent')
    expect(s).toBeDefined()
  })

  it('initialises with empty state', () => {
    const store = useAgentStore()
    expect(store.messages).toEqual([])
    expect(store.isLoading).toBe(false)
    expect(store.error).toBeNull()
    expect(store.hasMessages).toBe(false)
    expect(store.lastMessage).toBeNull()
  })

  it('addMessage appends to messages with correct shape', () => {
    const store = useAgentStore()
    const msg = store.addMessage('user', 'hello')
    expect(store.messages).toHaveLength(1)
    expect(msg.role).toBe('user')
    expect(msg.content).toBe('hello')
    expect(msg.id).toBeTruthy()
    expect(msg.timestamp).toBeInstanceOf(Date)
  })

  it('hasMessages is true after adding a message', () => {
    const store = useAgentStore()
    store.addMessage('user', 'test')
    expect(store.hasMessages).toBe(true)
  })

  it('lastMessage returns the most recent message', () => {
    const store = useAgentStore()
    store.addMessage('user', 'first')
    store.addMessage('assistant', 'second')
    expect(store.lastMessage?.content).toBe('second')
  })

  it('clearMessages resets messages and error', () => {
    const store = useAgentStore()
    store.addMessage('user', 'hi')
    store.clearMessages()
    expect(store.messages).toHaveLength(0)
    expect(store.error).toBeNull()
  })

  it('setModel updates selectedModel', () => {
    const store = useAgentStore()
    store.setModel('mistral')
    expect(store.selectedModel).toBe('mistral')
  })

  it('sendQuery adds user and assistant messages on success', async () => {
    const store = useAgentStore()
    const mockResponse: AgentResponse = {
      answer: 'CPU is at 42%.',
      query: 'CPU usage?',
      model: 'llama3',
    }
    vi.mocked(agentApi.query).mockResolvedValueOnce(mockResponse)

    await store.sendQuery('CPU usage?')

    expect(store.messages).toHaveLength(2)
    expect(store.messages[0]?.role).toBe('user')
    expect(store.messages[1]?.role).toBe('assistant')
    expect(store.messages[1]?.content).toBe('CPU is at 42%.')
    expect(store.isLoading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('sendQuery sets error on API failure', async () => {
    const store = useAgentStore()
    vi.mocked(agentApi.query).mockRejectedValueOnce({
      detail: 'Ollama unreachable',
      status: 502,
    })

    await store.sendQuery('test query')

    expect(store.error).toBe('Ollama unreachable')
    expect(store.isLoading).toBe(false)
    // User message still added
    expect(store.messages).toHaveLength(1)
  })

  it('sendQuery does nothing for blank input', async () => {
    const store = useAgentStore()
    await store.sendQuery('   ')
    expect(store.messages).toHaveLength(0)
    expect(agentApi.query).not.toHaveBeenCalled()
  })

  it('sendQuery passes context to api', async () => {
    const store = useAgentStore()
    vi.mocked(agentApi.query).mockResolvedValueOnce({
      answer: 'ok',
      query: 'q',
      model: 'llama3',
    })

    await store.sendQuery('q', { env: 'prod' })

    expect(vi.mocked(agentApi.query)).toHaveBeenCalledWith(
      expect.objectContaining({ context: { env: 'prod' } }),
    )
  })
})
