/**
 * Session / Grafana connectivity API calls.
 * All endpoints are relative — the Vite dev proxy forwards /api → backend.
 */

export interface ConnectivityResult {
  ok: boolean
  latencyMs?: number
  error?: string
}

export interface DatasourceInfo {
  uid: string
  name: string
  type: string
  is_default: boolean
}

export interface GrafanaConnectResult {
  session_id: string
  grafana_url: string
  datasources: DatasourceInfo[]
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

export async function connectGrafana(
  grafanaUrl: string,
  username: string,
  password: string,
  sessionId: string,
): Promise<GrafanaConnectResult> {
  const res = await fetch('/api/v1/grafana/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      grafana_url: grafanaUrl,
      username,
      password,
    }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(detail.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
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
