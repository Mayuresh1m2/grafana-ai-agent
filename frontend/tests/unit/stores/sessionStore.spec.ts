import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useSessionStore } from '@/stores/sessionStore'

// Stub localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem:   (k: string) => store[k] ?? null,
    setItem:   (k: string, v: string) => { store[k] = v },
    removeItem:(k: string) => { delete store[k] },
    clear:     () => { store = {} },
  }
})()
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

describe('useSessionStore — step validation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
  })

  it('initialises at step 1', () => {
    const s = useSessionStore()
    expect(s.step).toBe(1)
  })

  it('goToStep advances correctly', () => {
    const s = useSessionStore()
    s.goToStep(2)
    expect(s.step).toBe(2)
    s.goToStep(4)
    expect(s.step).toBe(4)
  })

  it('addService deduplicates and trims', () => {
    const s = useSessionStore()
    s.addService('api ')
    s.addService('api')
    expect(s.services).toHaveLength(1)
    expect(s.services[0]).toBe('api')
  })

  it('removeService removes by name', () => {
    const s = useSessionStore()
    s.addService('api')
    s.addService('db')
    s.removeService('api')
    expect(s.services).toEqual(['db'])
  })

  it('addService ignores blank strings', () => {
    const s = useSessionStore()
    s.addService('   ')
    expect(s.services).toHaveLength(0)
  })

  it('confirmSetup sets setupComplete and generates sessionId', () => {
    const s = useSessionStore()
    s.grafanaUrl.valueOf  // just access to confirm reactive
    s.confirmSetup()
    expect(s.setupComplete).toBe(true)
    expect(s.sessionId).toMatch(/^session_\d+$/)
  })

  it('resetSetup restores all defaults', () => {
    const s = useSessionStore()
    s.grafanaUrl = 'https://g.example.com'
    s.namespace  = 'prod'
    s.addService('web')
    s.confirmSetup()
    s.resetSetup()
    expect(s.step).toBe(1)
    expect(s.grafanaUrl).toBe('')
    expect(s.namespace).toBe('')
    expect(s.services).toHaveLength(0)
    expect(s.setupComplete).toBe(false)
    expect(s.sessionId).toBeNull()
    expect(s.authStatus).toBe('idle')
  })

  it('isReady is false when setup not complete', () => {
    const s = useSessionStore()
    s.grafanaUrl = 'https://g.example.com'
    s.namespace  = 'ns'
    // authStatus is still idle
    expect(s.isReady).toBe(false)
  })

  it('config computed returns all fields', () => {
    const s = useSessionStore()
    s.grafanaUrl  = 'https://g.io'
    s.namespace   = 'staging'
    s.environment = 'staging'
    const cfg = s.config
    expect(cfg.grafanaUrl).toBe('https://g.io')
    expect(cfg.namespace).toBe('staging')
    expect(cfg.environment).toBe('staging')
  })

  it('startAuthPoll sets authStatus to pending', () => {
    vi.useFakeTimers()
    const s = useSessionStore()
    s.startAuthPoll(async () => 'pending')
    expect(s.authStatus).toBe('pending')
    s.stopAuthPoll()
    vi.useRealTimers()
  })

  it('startAuthPoll resolves to complete and stops polling', async () => {
    vi.useFakeTimers()
    const s = useSessionStore()
    let calls = 0
    s.startAuthPoll(async () => {
      calls++
      return 'complete'
    })
    await vi.advanceTimersByTimeAsync(2500)
    expect(s.authStatus).toBe('complete')
    // Should not keep polling after complete
    const callsAfter = calls
    await vi.advanceTimersByTimeAsync(4000)
    expect(calls).toBe(callsAfter)
    vi.useRealTimers()
  })
})
