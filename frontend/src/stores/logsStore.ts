import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LogEntry } from '@/types/chat'

export const useLogsStore = defineStore('logs', () => {
  // service name → cached log entries
  const cache = ref<Record<string, LogEntry[]>>({})

  function setEntries(service: string, entries: LogEntry[]) {
    cache.value = { ...cache.value, [service]: entries }
  }

  function getEntries(service: string): LogEntry[] {
    return cache.value[service] ?? []
  }

  function appendEntries(service: string, entries: LogEntry[]) {
    const existing = cache.value[service] ?? []
    // Keep latest 500 entries per service
    const merged = [...existing, ...entries].slice(-500)
    cache.value = { ...cache.value, [service]: merged }
  }

  function clear(service?: string) {
    if (service) {
      const next = { ...cache.value }
      delete next[service]
      cache.value = next
    } else {
      cache.value = {}
    }
  }

  function errorCount(service: string): number {
    return (cache.value[service] ?? []).filter(
      (e) => e.level === 'error' || e.level === 'critical'
    ).length
  }

  return { cache, setEntries, getEntries, appendEntries, clear, errorCount }
})
