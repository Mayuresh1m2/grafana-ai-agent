// ─── SSE Event Types ────────────────────────────────────────────────────────
export type SSEEventType =
  | 'thinking'
  | 'content'
  | 'log_snippet'
  | 'metric'
  | 'code_ref'
  | 'suggestions'
  | 'done'
  | 'error'

export interface SSEThinkingEvent  { type: 'thinking'; chunk: string }
export interface SSEContentEvent   { type: 'content';  chunk: string }
export interface SSEDoneEvent      { type: 'done' }
export interface SSEErrorEvent     { type: 'error'; message: string; code?: string }

export interface SSELogSnippetEvent {
  type: 'log_snippet'
  service: string
  entries: LogEntry[]
}

export interface SSEMetricEvent {
  type: 'metric'
  name: string
  current: number
  threshold_warning: number
  threshold_critical: number
  unit: string
  series: number[]
  status: 'ok' | 'warn' | 'error'
}

export interface SSECodeRefEvent {
  type: 'code_ref'
  file_path: string
  line_start: number
  line_end: number
  snippet: string
  relevance_score: number
  repo_path?: string
}

export interface SSESuggestionsEvent {
  type: 'suggestions'
  items: string[]
}

export type SSEEvent =
  | SSEThinkingEvent
  | SSEContentEvent
  | SSELogSnippetEvent
  | SSEMetricEvent
  | SSECodeRefEvent
  | SSESuggestionsEvent
  | SSEDoneEvent
  | SSEErrorEvent

// ─── Message Artifacts ──────────────────────────────────────────────────────
export interface LogEntry {
  timestamp: number        // Unix seconds
  level: 'debug' | 'info' | 'warn' | 'error' | 'critical' | 'unknown'
  service: string
  message: string
  labels: Record<string, string>
}

export interface LogArtifact {
  kind: 'log'
  service: string
  entries: LogEntry[]
}

export interface MetricArtifact {
  kind: 'metric'
  name: string
  current: number
  threshold_warning: number
  threshold_critical: number
  unit: string
  series: number[]
  status: 'ok' | 'warn' | 'error'
}

export interface CodeRefArtifact {
  kind: 'code_ref'
  file_path: string
  line_start: number
  line_end: number
  snippet: string
  relevance_score: number
  repo_path?: string
}

export type Artifact = LogArtifact | MetricArtifact | CodeRefArtifact

// ─── Chat Messages ──────────────────────────────────────────────────────────
export interface ThinkingState {
  chunks: string[]          // growing array of raw text chunks
  isDone: boolean
  collapsed: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string           // markdown for assistant, plain for user
  thinking: ThinkingState | null
  artifacts: Artifact[]
  suggestions: string[]     // follow-up question chips
  timestamp: Date
  status: 'complete' | 'streaming' | 'error'
  errorMessage?: string
}

// ─── Session Types ──────────────────────────────────────────────────────────
export type SetupStep = 1 | 2 | 3 | 4

export type Environment = 'prod' | 'staging' | 'dev' | 'custom'

export type AuthStatus = 'idle' | 'pending' | 'complete' | 'failed'

export interface SessionConfig {
  grafanaUrl: string
  namespace: string
  environment: Environment
  services: string[]
  repoPath: string
  sessionId: string | null
}

// ─── Metric series ──────────────────────────────────────────────────────────
export interface MetricSeries {
  service: string
  metric: string
  values: { timestamp: number; value: number }[]
  updatedAt: Date
}
