import { apiClient } from './client'
import type { AgentQuery, AgentResponse } from '@/types/agent'
import type { HealthResponse } from '@/types/api'

export const agentApi = {
  async query(payload: AgentQuery): Promise<AgentResponse> {
    const { data } = await apiClient.post<AgentResponse>('/agent/query', {
      query: payload.query,
      context: payload.context ?? {},
      model: payload.model ?? null,
      temperature: payload.temperature ?? 0.7,
      max_tokens: payload.maxTokens ?? 2048,
    })
    return data
  },

  async health(): Promise<HealthResponse> {
    const { data } = await apiClient.get<HealthResponse>('/health/')
    return data
  },
}
