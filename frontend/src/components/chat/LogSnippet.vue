<script setup lang="ts">
import { ref } from 'vue'
import type { LogArtifact, LogEntry } from '@/types/chat'

defineProps<{ artifact: LogArtifact }>()

const copied = ref(false)

const LEVEL_CLASS: Record<LogEntry['level'], string> = {
  debug:    'log--debug',
  info:     'log--info',
  warn:     'log--warn',
  error:    'log--error',
  critical: 'log--critical',
  unknown:  'log--unknown',
}

function formatTs(unix: number): string {
  return new Date(unix * 1000).toISOString().replace('T', ' ').slice(0, 23)
}

async function copy(entries: LogEntry[]) {
  const text = entries
    .map((e) => `${formatTs(e.timestamp)} [${e.level.toUpperCase()}] ${e.message}`)
    .join('\n')
  await navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <div class="log-snippet">
    <div class="log-snippet__header">
      <span class="log-snippet__service">{{ artifact.service }}</span>
      <span class="log-snippet__count">{{ artifact.entries.length }} lines</span>
      <button class="log-snippet__copy btn-ghost" @click="copy(artifact.entries)">
        {{ copied ? 'Copied!' : 'Copy' }}
      </button>
    </div>
    <div class="log-snippet__body">
      <div
        v-for="(entry, i) in artifact.entries"
        :key="i"
        class="log-row"
        :class="LEVEL_CLASS[entry.level]"
      >
        <span class="log-row__ts">{{ formatTs(entry.timestamp) }}</span>
        <span class="log-row__lvl">{{ entry.level.toUpperCase() }}</span>
        <span class="log-row__msg">{{ entry.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-snippet {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 0.78rem;
}

.log-snippet__header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.4rem 0.75rem;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
}

.log-snippet__service {
  font-weight: 600;
  color: var(--accent-blue);
  flex: 1;
}

.log-snippet__count { color: var(--text-muted); font-size: 0.75rem; }

.log-snippet__copy {
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  font-family: var(--font-sans);
}

.log-snippet__body {
  max-height: 240px;
  overflow-y: auto;
  background: var(--surface);
}

.log-row {
  display: grid;
  grid-template-columns: 14ch 8ch 1fr;
  gap: 0.75rem;
  padding: 0.2rem 0.75rem;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  line-height: 1.5;
}
.log-row:last-child { border-bottom: none; }

.log-row__ts  { color: var(--text-muted); white-space: nowrap; }
.log-row__msg { word-break: break-all; color: var(--text); }

/* Level colours */
.log-row__lvl { font-weight: 600; }
.log--debug    .log-row__lvl { color: var(--text-muted); }
.log--info     .log-row__lvl { color: var(--accent-blue); }
.log--warn     .log-row__lvl { color: var(--status-warn); }
.log--error    .log-row__lvl { color: var(--status-error); }
.log--critical .log-row__lvl { color: var(--status-error); }
.log--critical { background: rgba(255, 77, 106, 0.04); }
.log--unknown  .log-row__lvl { color: var(--text-muted); }
</style>
