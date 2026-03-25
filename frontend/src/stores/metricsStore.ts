import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MetricSeries, MetricArtifact } from '@/types/chat'

export const useMetricsStore = defineStore('metrics', () => {
  // key: `${service}::${metric}`
  const series = ref<Record<string, MetricSeries>>({})

  function _key(service: string, metric: string) {
    return `${service}::${metric}`
  }

  function upsertFromArtifact(service: string, artifact: MetricArtifact) {
    const k = _key(service, artifact.name)
    const existing = series.value[k]
    const now = Date.now() / 1000
    const newPoint = { timestamp: now, value: artifact.current }
    const values = existing
      ? [...existing.values, newPoint].slice(-200)
      : artifact.series.map((v, i) => ({
          timestamp: now - (artifact.series.length - 1 - i),
          value: v,
        }))
    series.value = {
      ...series.value,
      [k]: { service, metric: artifact.name, values, updatedAt: new Date() },
    }
  }

  function getSeries(service: string, metric: string): MetricSeries | null {
    return series.value[_key(service, metric)] ?? null
  }

  function getValues(service: string, metric: string): number[] {
    return getSeries(service, metric)?.values.map((v) => v.value) ?? []
  }

  function clear(service?: string) {
    if (service) {
      const next = { ...series.value }
      Object.keys(next).forEach((k) => {
        if (k.startsWith(`${service}::`)) delete next[k]
      })
      series.value = next
    } else {
      series.value = {}
    }
  }

  return { series, upsertFromArtifact, getSeries, getValues, clear }
})
