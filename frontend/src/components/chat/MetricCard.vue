<script setup lang="ts">
import { ref, computed } from 'vue'
import { useSparkline } from '@/composables/useSparkline'
import type { MetricArtifact } from '@/types/chat'

const props = defineProps<{ artifact: MetricArtifact }>()

const canvas = ref<HTMLCanvasElement | null>(null)
const seriesRef = computed(() => props.artifact.series)

const statusColor: Record<string, string> = {
  ok:    'var(--status-ok)',
  warn:  'var(--status-warn)',
  error: 'var(--status-error)',
}

useSparkline(canvas, seriesRef, {
  color:             statusColor[props.artifact.status] ?? 'var(--accent-blue)',
  lineWidth:         1.5,
  thresholdWarn:     props.artifact.threshold_warning,
  thresholdCritical: props.artifact.threshold_critical,
})

function fmt(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000)     return `${(v / 1_000).toFixed(1)}k`
  return v % 1 === 0  ? String(v) : v.toFixed(2)
}
</script>

<template>
  <div class="metric-card" :class="`metric-card--${artifact.status}`">
    <div class="metric-card__left">
      <span class="metric-card__name">{{ artifact.name }}</span>
      <span class="metric-card__value">
        {{ fmt(artifact.current) }}
        <span class="metric-card__unit">{{ artifact.unit }}</span>
      </span>
      <div class="metric-card__thresholds">
        <span class="warn-badge">W {{ fmt(artifact.threshold_warning) }}</span>
        <span class="crit-badge">C {{ fmt(artifact.threshold_critical) }}</span>
      </div>
    </div>
    <div class="metric-card__chart">
      <canvas ref="canvas" width="120" height="48" />
    </div>
  </div>
</template>

<style scoped>
.metric-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  min-width: 260px;
}

.metric-card--warn  { border-color: rgba(255, 179, 71, 0.4); }
.metric-card--error { border-color: rgba(255, 77, 106, 0.4); }

.metric-card__left {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex: 1;
  min-width: 0;
}

.metric-card__name {
  font-size: 0.75rem;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric-card__value {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.metric-card__unit {
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--text-muted);
  margin-left: 0.25rem;
}

.metric-card--ok    .metric-card__value { color: var(--status-ok); }
.metric-card--warn  .metric-card__value { color: var(--status-warn); }
.metric-card--error .metric-card__value { color: var(--status-error); }

.metric-card__thresholds {
  display: flex;
  gap: 0.4rem;
  font-size: 0.7rem;
}

.warn-badge { color: var(--status-warn); }
.crit-badge { color: var(--status-error); }

.metric-card__chart canvas {
  display: block;
}
</style>
