/**
 * Session / Grafana connectivity API calls.
 * All endpoints are relative — the Vite dev proxy forwards /api → backend.
 */

export interface ConnectivityResult {
  ok: boolean
  latencyMs?: number
  error?: string
}

export interface AuthInitResult {
  authUrl: string
  state: string
}

export type AuthPollStatus = 'pending' | 'complete' | 'failed'

export interface AuthPollResult {
  status: AuthPollStatus
}

export async function checkConnectivity(grafanaUrl: string): Promise<ConnectivityResult> {
  const res = await fetch('/api/v1/session/connectivity', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ grafana_url: grafanaUrl }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function initAuth(grafanaUrl: string): Promise<AuthInitResult> {
  const res = await fetch('/api/v1/session/auth/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ grafana_url: grafanaUrl }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function pollAuth(state: string): Promise<AuthPollStatus> {
  const res = await fetch(`/api/v1/session/auth/status?state=${encodeURIComponent(state)}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data: AuthPollResult = await res.json()
  return data.status
}

export async function fetchNamespaces(grafanaUrl: string): Promise<string[]> {
  const res = await fetch('/api/v1/session/namespaces', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ grafana_url: grafanaUrl }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data: { namespaces: string[] } = await res.json()
  return data.namespaces
}
