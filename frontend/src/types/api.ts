export interface ApiError {
  detail: string
  status: number
}

export interface HealthResponse {
  status: string
  version: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
}
