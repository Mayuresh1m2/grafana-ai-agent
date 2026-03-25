<script setup lang="ts">
import { ref } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import { connectGrafana } from '@/api/session'

const session = useSessionStore()

const username   = ref('')
const password   = ref('')
const connecting = ref(false)
const error      = ref<string | null>(null)

async function submit() {
  if (!username.value || !password.value) return
  error.value      = null
  connecting.value = true

  // Generate a stable session ID if not already set
  if (!session.sessionId) {
    session.sessionId = `session_${Date.now()}`
  }

  try {
    await connectGrafana(
      session.grafanaUrl,
      username.value,
      password.value,
      session.sessionId as string,
    )
    session.authStatus = 'complete'
    session.goToStep(3)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    session.authStatus = 'failed'
  } finally {
    connecting.value = false
  }
}

function back() {
  session.authStatus = 'idle'
  session.goToStep(1)
}
</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Authenticate with Grafana</h2>
    <p class="step-panel__desc">
      Enter your Grafana credentials. The agent uses headless Chrome to log in
      and obtain a session cookie — your password is never stored.
    </p>

    <form class="auth-form" @submit.prevent="submit">
      <label class="field">
        <span class="field__label">Username / e-mail</span>
        <input
          v-model="username"
          type="text"
          autocomplete="username"
          placeholder="admin"
          class="field__input"
          :disabled="connecting"
        />
      </label>

      <label class="field">
        <span class="field__label">Password</span>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          placeholder="••••••••"
          class="field__input"
          :disabled="connecting"
        />
      </label>

      <div v-if="connecting" class="auth-polling">
        <span class="spinner" aria-label="Logging in…" />
        <span class="auth-polling__text">Logging in via headless browser…</span>
      </div>

      <p v-if="error" class="status-error">{{ error }}</p>
      <p v-if="session.authStatus === 'complete'" class="status-ok">
        Authenticated successfully
      </p>

      <div class="step-panel__nav">
        <button type="button" class="btn-ghost" :disabled="connecting" @click="back">
          Back
        </button>
        <button
          type="submit"
          class="btn-primary"
          :disabled="connecting || !username || !password"
        >
          {{ connecting ? 'Connecting…' : 'Connect' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__nav   { display: flex; gap: 0.75rem; margin-top: 0.5rem; }

.auth-form { display: flex; flex-direction: column; gap: 0.75rem; }

.field { display: flex; flex-direction: column; gap: 0.3rem; }
.field__label { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
.field__input {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  color: var(--text);
  font-size: 0.9rem;
  outline: none;
}
.field__input:focus { border-color: var(--accent-blue); }
.field__input:disabled { opacity: 0.6; cursor: not-allowed; }

.status-ok    { font-size: 0.85rem; color: var(--status-ok); margin: 0; }
.status-error { font-size: 0.85rem; color: var(--status-error); margin: 0; }

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
