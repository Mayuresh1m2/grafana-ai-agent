<script setup lang="ts">
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore }    from '@/stores/chatStore'
import { useRouter }       from 'vue-router'

const session = useSessionStore()
const chat    = useChatStore()
const router  = useRouter()

const emit = defineEmits<{
  (e: 'quick-action', q: string): void
  (e: 'generate-report'): void
}>()

const QUICK_ACTIONS = [
  'What services are currently alerting?',
  'Show me recent error logs',
  'What are the current CPU metrics?',
  'Any anomalies in the last hour?',
]

// emit is already defined above

function goSetup() {
  session.resetSetup()
  router.push('/setup')
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar__section">
      <p class="sidebar__label">Session</p>
      <ul class="sidebar__meta">
        <li>
          <span class="meta-key">URL</span>
          <span class="meta-val truncate">{{ session.grafanaUrl || '—' }}</span>
        </li>
        <li>
          <span class="meta-key">Namespace</span>
          <span class="meta-val">{{ session.namespace || '—' }}</span>
        </li>
        <li>
          <span class="meta-key">Env</span>
          <span class="meta-val">{{ session.environment }}</span>
        </li>
        <li v-if="session.services.length">
          <span class="meta-key">Services</span>
          <span class="meta-val">{{ session.services.join(', ') }}</span>
        </li>
      </ul>
    </div>

    <!-- Active alerts -->
    <div class="sidebar__section">
      <p class="sidebar__label">
        Active alerts
        <span v-if="session.alertsLoading" class="alerts-spinner" />
        <span v-else-if="session.alerts.length" class="alerts-count">
          {{ session.alerts.length }}
        </span>
      </p>

      <p v-if="!session.alertsLoading && !session.alerts.length" class="sidebar__no-alerts">
        No firing alerts
      </p>

      <ul v-else class="sidebar__alerts">
        <li
          v-for="alert in session.alerts"
          :key="alert.name + (alert.started_at ?? '')"
          class="alert-row"
          :title="alert.summary || alert.name"
          @click="emit('quick-action', `Tell me about the ${alert.name} alert`)"
        >
          <span :class="['alert-badge', `alert-badge--${alert.severity}`]">
            {{ alert.severity === 'unknown' ? '!' : alert.severity[0].toUpperCase() }}
          </span>
          <span class="alert-name">{{ alert.name }}</span>
        </li>
      </ul>

      <button
        v-if="!session.alertsLoading"
        class="sidebar__refresh-btn"
        title="Refresh alerts"
        @click="session.loadAlerts()"
      >
        ↻ Refresh
      </button>
    </div>

    <div class="sidebar__section">
      <p class="sidebar__label">Quick actions</p>
      <ul class="sidebar__actions">
        <li v-for="q in QUICK_ACTIONS" :key="q">
          <button class="sidebar__action-btn" @click="emit('quick-action', q)">
            {{ q }}
          </button>
        </li>
      </ul>
    </div>

    <div class="sidebar__footer">
      <button
        class="btn-primary sidebar__report-btn"
        :disabled="!chat.hasMessages || chat.isStreaming"
        title="Generate post-incident report from this investigation"
        @click="emit('generate-report')"
      >
        Generate Report
      </button>
      <button class="btn-ghost sidebar__clear" @click="chat.clearMessages">
        Clear chat
      </button>
      <button class="btn-ghost sidebar__reconfigure" @click="goSetup">
        Reconfigure
      </button>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow-y: auto;
}

.sidebar__section {
  padding: 1rem;
  border-bottom: 1px solid var(--border);
}

.sidebar__label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 0.5rem;
}

.sidebar__meta {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.sidebar__meta li {
  display: flex;
  gap: 0.4rem;
  font-size: 0.78rem;
  line-height: 1.4;
}

.meta-key {
  color: var(--text-muted);
  flex-shrink: 0;
  width: 5rem;
}

.meta-val {
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar__actions {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.sidebar__action-btn {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.4rem 0.5rem;
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: 0.78rem;
  cursor: pointer;
  border-radius: var(--radius-sm);
  line-height: 1.4;
  transition: background 0.12s, color 0.12s;
}
.sidebar__action-btn:hover {
  background: var(--surface-2);
  color: var(--text);
}

.sidebar__footer {
  margin-top: auto;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  border-top: 1px solid var(--border);
}

.sidebar__report-btn {
  font-size: 0.78rem;
  padding: 0.4rem 0.5rem;
  width: 100%;
  justify-content: center;
}
.sidebar__clear,
.sidebar__reconfigure {
  font-size: 0.78rem;
  padding: 0.35rem 0.5rem;
  justify-content: flex-start;
}

/* Alerts section */
.sidebar__label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.alerts-count {
  margin-left: auto;
  background: var(--status-error, #ef4444);
  color: #fff;
  border-radius: 9999px;
  font-size: 0.65rem;
  font-weight: 700;
  padding: 0.1rem 0.4rem;
  line-height: 1.4;
}

.alerts-spinner {
  margin-left: auto;
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.sidebar__no-alerts {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0;
}

.sidebar__alerts {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-bottom: 0.4rem;
}

.alert-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.4rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.1s;
}
.alert-row:hover { background: var(--surface-2); }

.alert-badge {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.6rem;
  font-weight: 700;
  color: #fff;
}
.alert-badge--critical  { background: var(--status-error,   #ef4444); }
.alert-badge--warning   { background: var(--status-warning, #f59e0b); }
.alert-badge--info      { background: var(--accent-blue,    #3b82f6); }
.alert-badge--unknown   { background: var(--text-muted,     #6b7280); }

.alert-name {
  font-size: 0.75rem;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar__refresh-btn {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 0.72rem;
  cursor: pointer;
  padding: 0.15rem 0;
  transition: color 0.1s;
}
.sidebar__refresh-btn:hover { color: var(--text); }
</style>
