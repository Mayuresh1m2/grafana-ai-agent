/**
 * Chat / agent API.
 * The SSE streaming endpoint is consumed via useSSE (not here).
 * This file covers any non-streaming chat endpoints.
 */

export interface SessionPayload {
  session_id: string | null
  grafana_url: string
  namespace: string
  environment: string
  services: string[]
  repo_path: string
}

export async function clearSession(sessionId: string): Promise<void> {
  const res = await fetch(`/api/v1/agent/session/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

export async function getSessionHistory(sessionId: string): Promise<{ messages: unknown[] }> {
  const res = await fetch(`/api/v1/agent/session/${encodeURIComponent(sessionId)}/history`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
