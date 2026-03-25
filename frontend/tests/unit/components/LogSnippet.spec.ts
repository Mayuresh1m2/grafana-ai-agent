import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import LogSnippet from '@/components/chat/LogSnippet.vue'
import type { LogArtifact } from '@/types/chat'

const artifact: LogArtifact = {
  kind: 'log',
  service: 'api-gateway',
  entries: [
    { timestamp: 1700000000, level: 'error',  service: 'api-gateway', message: 'Connection refused', labels: {} },
    { timestamp: 1700000001, level: 'info',   service: 'api-gateway', message: 'Retrying…',          labels: {} },
    { timestamp: 1700000002, level: 'warn',   service: 'api-gateway', message: 'Slow response 2.3s', labels: {} },
  ],
}

describe('LogSnippet', () => {
  it('renders service name', () => {
    const w = mount(LogSnippet, { props: { artifact } })
    expect(w.text()).toContain('api-gateway')
  })

  it('renders correct entry count', () => {
    const w = mount(LogSnippet, { props: { artifact } })
    expect(w.text()).toContain('3 lines')
  })

  it('renders all log rows', () => {
    const w = mount(LogSnippet, { props: { artifact } })
    expect(w.findAll('.log-row')).toHaveLength(3)
  })

  it('applies error CSS class to error rows', () => {
    const w = mount(LogSnippet, { props: { artifact } })
    const rows = w.findAll('.log-row')
    expect(rows[0]!.classes()).toContain('log--error')
    expect(rows[1]!.classes()).toContain('log--info')
    expect(rows[2]!.classes()).toContain('log--warn')
  })

  describe('clipboard copy', () => {
    beforeEach(() => {
      Object.defineProperty(globalThis.navigator, 'clipboard', {
        value: { writeText: vi.fn().mockResolvedValue(undefined) },
        configurable: true,
      })
      vi.useFakeTimers()
    })

    it('calls clipboard.writeText with formatted log lines', async () => {
      const w = mount(LogSnippet, { props: { artifact } })
      await w.find('.log-snippet__copy').trigger('click')
      expect(navigator.clipboard.writeText).toHaveBeenCalledOnce()
      const text = vi.mocked(navigator.clipboard.writeText).mock.calls[0]![0]
      expect(text).toContain('Connection refused')
      expect(text).toContain('[ERROR]')
    })

    it('shows "Copied!" feedback then reverts', async () => {
      const w = mount(LogSnippet, { props: { artifact } })
      await w.find('.log-snippet__copy').trigger('click')
      // Flush the microtask for clipboard.writeText
      await Promise.resolve()
      expect(w.find('.log-snippet__copy').text()).toBe('Copied!')
      vi.advanceTimersByTime(1600)
      await w.vm.$nextTick()
      expect(w.find('.log-snippet__copy').text()).toBe('Copy')
    })
  })
})
