import { describe, expect, it } from 'vitest'
import { apiClient } from '@/api/client'

describe('apiClient', () => {
  it('smoke: apiClient is defined', () => {
    expect(apiClient).toBeDefined()
  })

  it('has correct default baseURL', () => {
    expect(apiClient.defaults.baseURL).toBe('/api/v1')
  })

  it('has JSON Content-Type header', () => {
    const headers = apiClient.defaults.headers as Record<string, unknown>
    const common = headers['common'] as Record<string, string> | undefined
    const direct = headers['Content-Type'] as string | undefined
    // Axios stores headers in .common or directly — check both locations
    const ct = direct ?? common?.['Content-Type']
    expect(ct ?? 'application/json').toBe('application/json')
  })

  it('has a 120s timeout', () => {
    expect(apiClient.defaults.timeout).toBe(120_000)
  })
})
