export type MessageRole = 'user' | 'assistant' | 'system'

export interface AgentQuery {
  query: string
  context?: Record<string, string>
  model?: string
  temperature?: number
  maxTokens?: number
}

export interface AgentResponse {
  answer: string
  query: string
  model: string
  tokensUsed?: number
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  timestamp: Date
}
