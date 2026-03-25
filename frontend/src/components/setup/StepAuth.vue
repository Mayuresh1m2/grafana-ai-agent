<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import { initAuth, pollAuth } from '@/api/session'

const session = useSessionStore()

const authState  = ref<string | null>(null)
const authUrl    = ref<string | null>(null)
const initError  = ref<string | null>(null)
const initiating = ref(false)

async function startAuth() {
  initError.value  = null
  initiating.value = true
  try {
    const result = await initAuth(session.grafanaUrl)
    authUrl.value   = result.authUrl
    authState.value = result.state
    window.open(result.authUrl, '_blank', 'noopener,noreferrer')

    session.startAuthPoll(async () => {
      if (!authState.value) return 'failed'
      return pollAuth(authState.value)
    })
  } catch (e) {
    initError.value = e instanceof Error ? e.message : String(e)
  } finally {
    initiating.value = false
  }
}

function next() {
  if (session.authStatus === 'complete') session.goToStep(3)
}

function back() {
  session.stopAuthPoll()
  session.goToStep(1)
}

onUnmounted(() => session.stopAuthPoll())
</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Authenticate with Grafana</h2>
    <p class="step-panel__desc">
      Open the Grafana OAuth flow in your browser. This page will detect
      completion automatically (checked every 2 seconds).
    </p>

    <div v-if="session.authStatus === 'idle' || session.authStatus === 'failed'" class="step-panel__actions">
      <button class="btn-primary" :disabled="initiating" @click="startAuth">
        {{ initiating ? 'Opening…' : 'Open Grafana login' }}
      </button>
    </div>

    <div v-else-if="session.authStatus === 'pending'" class="auth-polling">
      <span class="spinner" aria-label="Waiting for authentication…" />
      <span class="auth-polling__text">Waiting for login to complete…</span>
    </div>

    <p v-if="session.authStatus === 'complete'" class="status-ok">
      Authenticated successfully
    </p>
    <p v-else-if="session.authStatus === 'failed'" class="status-error">
      Authentication failed. Please try again.
    </p>
    <p v-if="initError" class="status-error">{{ initError }}</p>

    <div class="step-panel__nav">
      <button class="btn-ghost" @click="back">Back</button>
      <button class="btn-primary" :disabled="session.authStatus !== 'complete'" @click="next">
        Next
      </button>
    </div>
  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__actions { display: flex; gap: 0.75rem; }
.step-panel__nav { display: flex; gap: 0.75rem; margin-top: 0.5rem; }
.status-ok    { font-size: 0.85rem; color: var(--status-ok); }
.status-error { font-size: 0.85rem; color: var(--status-error); }

.auth-polling {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  background: var(--surface-2);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}

.auth-polling__text { font-size: 0.9rem; color: var(--text-muted); }

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin { to { transform: rotate(360deg); } }
</style>
