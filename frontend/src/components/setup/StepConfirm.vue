<script setup lang="ts">
import { useSessionStore } from '@/stores/sessionStore'
import { useRouter } from 'vue-router'

const session = useSessionStore()
const router  = useRouter()

function back() { session.goToStep(3) }

function confirm() {
  session.confirmSetup()
  router.push('/')
}
</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Confirm setup</h2>
    <p class="step-panel__desc">Review your configuration before starting a session.</p>

    <dl class="summary">
      <div class="summary__row">
        <dt>Grafana URL</dt>
        <dd>{{ session.grafanaUrl }}</dd>
      </div>
      <div class="summary__row">
        <dt>Auth status</dt>
        <dd :class="session.authStatus === 'complete' ? 'ok' : 'warn'">
          {{ session.authStatus }}
        </dd>
      </div>
      <div class="summary__row">
        <dt>Namespace</dt>
        <dd>{{ session.namespace || '—' }}</dd>
      </div>
      <div class="summary__row">
        <dt>Environment</dt>
        <dd>{{ session.environment }}</dd>
      </div>
      <div class="summary__row">
        <dt>Services</dt>
        <dd>{{ session.services.length ? session.services.join(', ') : '—' }}</dd>
      </div>
      <div class="summary__row">
        <dt>Repo path</dt>
        <dd>{{ session.repoPath || '—' }}</dd>
      </div>
    </dl>

    <div class="step-panel__nav">
      <button class="btn-ghost" @click="back">Back</button>
      <button class="btn-primary" @click="confirm">Start session</button>
    </div>
  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1.25rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__nav   { display: flex; gap: 0.75rem; }

.summary {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin: 0;
}

.summary__row {
  display: flex;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
}
.summary__row:last-child { border-bottom: none; }

.summary__row dt {
  width: 9rem;
  flex-shrink: 0;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-muted);
  padding-top: 0.05rem;
}

.summary__row dd {
  font-size: 0.9rem;
  color: var(--text);
  word-break: break-all;
  margin: 0;
}

.ok   { color: var(--status-ok); }
.warn { color: var(--status-warn); }
</style>
