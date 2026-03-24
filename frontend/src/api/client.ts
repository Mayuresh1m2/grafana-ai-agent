import axios, { type AxiosInstance, type AxiosError } from 'axios'
import type { ApiError } from '@/types/api'

const BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'

export const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 120_000,
})

// Normalise all error responses to ApiError
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail: string }>) => {
    const apiError: ApiError = {
      detail: error.response?.data?.detail ?? error.message,
      status: error.response?.status ?? 0,
    }
    return Promise.reject(apiError)
  },
)
