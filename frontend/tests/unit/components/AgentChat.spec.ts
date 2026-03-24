import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentChat from '@/components/AgentChat.vue'
import type { ChatMessage } from '@/types/agent'

function makeMsg(
  role: ChatMessage['role'],
  content: string,
  id = crypto.randomUUID(),
): ChatMessage {
  return { id, role, content, timestamp: new Date() }
}

describe('AgentChat', () => {
  it('smoke: component mounts without errors', () => {
    const wrapper = mount(AgentChat, {
      props: { messages: [], isLoading: false },
    })
    expect(wrapper.exists()).toBe(true)
  })

  it('shows empty state when messages is empty and not loading', () => {
    const wrapper = mount(AgentChat, {
      props: { messages: [], isLoading: false },
    })
    expect(wrapper.text()).toContain('Ask a question')
  })

  it('does not show empty state when messages are present', () => {
    const wrapper = mount(AgentChat, {
      props: {
        messages: [makeMsg('user', 'hello')],
        isLoading: false,
      },
    })
    expect(wrapper.find('.empty-state').exists()).toBe(false)
  })

  it('renders user message content', () => {
    const wrapper = mount(AgentChat, {
      props: {
        messages: [makeMsg('user', 'What is the CPU?')],
        isLoading: false,
      },
    })
    expect(wrapper.text()).toContain('What is the CPU?')
  })

  it('renders assistant message content', () => {
    const wrapper = mount(AgentChat, {
      props: {
        messages: [makeMsg('assistant', 'CPU is at 42%.')],
        isLoading: false,
      },
    })
    expect(wrapper.text()).toContain('CPU is at 42%.')
  })

  it('applies message--user class to user messages', () => {
    const wrapper = mount(AgentChat, {
      props: {
        messages: [makeMsg('user', 'hi')],
        isLoading: false,
      },
    })
    expect(wrapper.find('.message--user').exists()).toBe(true)
  })

  it('applies message--assistant class to assistant messages', () => {
    const wrapper = mount(AgentChat, {
      props: {
        messages: [makeMsg('assistant', 'hello')],
        isLoading: false,
      },
    })
    expect(wrapper.find('.message--assistant').exists()).toBe(true)
  })

  it('shows loading indicator when isLoading is true', () => {
    const wrapper = mount(AgentChat, {
      props: { messages: [], isLoading: true },
    })
    expect(wrapper.find('.loading').exists()).toBe(true)
  })

  it('does not show loading indicator when isLoading is false', () => {
    const wrapper = mount(AgentChat, {
      props: { messages: [], isLoading: false },
    })
    expect(wrapper.find('.loading').exists()).toBe(false)
  })

  it('renders multiple messages in order', () => {
    const messages: ChatMessage[] = [
      makeMsg('user', 'first', '1'),
      makeMsg('assistant', 'second', '2'),
      makeMsg('user', 'third', '3'),
    ]
    const wrapper = mount(AgentChat, { props: { messages, isLoading: false } })
    const articles = wrapper.findAll('article')
    expect(articles).toHaveLength(3)
  })
})
