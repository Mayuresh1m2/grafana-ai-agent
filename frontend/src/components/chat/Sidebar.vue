<script setup lang="ts">
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore }    from '@/stores/chatStore'
import { useRouter }       from 'vue-router'

const session = useSessionStore()
const chat    = useChatStore()
const router  = useRouter()

const QUICK_ACTIONS = [
  'What services are currently alerting?',
  'Show me recent error logs',
  'What are the current CPU metrics?',
  'Any anomalies in the last hour?',
]

const emit = defineEmits<{ (e: 'quick-action', q: string): void }>()

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

.sidebar__clear,
.sidebar__reconfigure {
  font-size: 0.78rem;
  padding: 0.35rem 0.5rem;
  justify-content: flex-start;
}
</style>
