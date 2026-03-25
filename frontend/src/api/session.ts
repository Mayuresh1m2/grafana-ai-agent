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

export interface AlertInfo {
  name: string
  severity: 'critical' | 'warning' | 'info' | 'unknown'
  state: string
  summary: string
  labels: Record<string, string>
  started_at: string | null
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

async function _postConnect(body: Record<string, string>): Promise<GrafanaConnectResult> {
  const res = await fetch('/api/v1/grafana/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(typeof detail.detail === 'string' ? detail.detail : `HTTP ${res.status}`)
  }
  return res.json()
}

export async function connectGrafana(
  grafanaUrl: string,
  username: string,
  password: string,
  sessionId: string,
): Promise<GrafanaConnectResult> {
  return _postConnect({ session_id: sessionId, grafana_url: grafanaUrl, username, password })
}

export async function connectGrafanaCookie(
  grafanaUrl: string,
  cookieHeader: string,
  sessionId: string,
): Promise<GrafanaConnectResult> {
  return _postConnect({ session_id: sessionId, grafana_url: grafanaUrl, cookie_header: cookieHeader })
}

export async function connectGrafanaAzureCli(
  grafanaUrl: string,
  azureScope: string,
  sessionId: string,
): Promise<GrafanaConnectResult> {
  return _postConnect({ session_id: sessionId, grafana_url: grafanaUrl, azure_scope: azureScope })
}

export async function connectGrafanaServiceToken(
  grafanaUrl: string,
  token: string,
  sessionId: string,
): Promise<GrafanaConnectResult> {
  return _postConnect({ session_id: sessionId, grafana_url: grafanaUrl, service_account_token: token })
}

export async function refreshGrafanaCookie(
  sessionId: string,
  cookieHeader: string,
): Promise<GrafanaConnectResult> {
  const res = await fetch('/api/v1/grafana/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, cookie_header: cookieHeader }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(typeof detail.detail === 'string' ? detail.detail : `HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchAlerts(sessionId: string): Promise<AlertInfo[]> {
  const res = await fetch(`/api/v1/grafana/alerts?session_id=${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
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
