<script setup lang="ts">
import { ref } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import { refreshGrafanaCookie } from '@/api/session'

const emit = defineEmits<{ (e: 'refreshed'): void }>()

const session     = useSessionStore()
const expanded    = ref(false)
const cookieInput = ref('')
const refreshing  = ref(false)
const error       = ref<string | null>(null)

async function submit() {
  if (!cookieInput.value.trim() || !session.sessionId) return
  error.value    = null
  refreshing.value = true
  try {
    await refreshGrafanaCookie(session.sessionId, cookieInput.value.trim())
    cookieInput.value = ''
    expanded.value    = false
    emit('refreshed')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    refreshing.value = false
  }
}
</script>

<template>
  <div class="expired-banner">
    <div class="expired-banner__row">
      <span class="expired-banner__icon" aria-hidden="true">⚠</span>
      <span class="expired-banner__msg">Grafana session expired — queries will fail until you refresh.</span>
      <button class="btn-primary btn--sm" @click="expanded = !expanded">
        {{ expanded ? 'Cancel' : 'Refresh session' }}
      </button>
    </div>

    <Transition name="slide">
      <div v-if="expanded" class="expired-banner__form">
        <div class="cookie-guide">
          <p class="cookie-guide__title">Paste a fresh Grafana cookie:</p>
          <ol class="cookie-guide__steps">
            <li>Open Grafana in your browser and log in with Microsoft SSO</li>
            <li>Press <kbd>F12</kbd> → <strong>Network</strong> tab → reload the page</li>
            <li>Click any Grafana request → <strong>Headers → Request Headers → Cookie</strong></li>
            <li>Right-click → <em>Copy value</em></li>
          </ol>
        </div>

        <textarea
          v-model="cookieInput"
          rows="2"
          class="cookie-input"
          placeholder="grafana_session=abc123; grafana_session_expiry=…"
          :disabled="refreshing"
        />

        <p v-if="error" class="status-error">{{ error }}</p>

        <button
          class="btn-primary btn--sm"
          :disabled="refreshing || !cookieInput.trim()"
          @click="submit"
        >
          {{ refreshing ? 'Validating…' : 'Reconnect' }}
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.expired-banner {
  background: color-mix(in srgb, var(--status-warning, #f59e0b) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--status-warning, #f59e0b) 40%, transparent);
  border-radius: var(--radius);
  padding: 0.6rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin: 0.5rem 1rem;
}

.expired-banner__row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.expired-banner__icon { font-size: 0.9rem; flex-shrink: 0; }
.expired-banner__msg  { flex: 1; font-size: 0.875rem; min-width: 180px; }

.expired-banner__form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.cookie-guide {
  font-size: 0.82rem;
  background: var(--surface-1);
  border-radius: var(--radius);
  padding: 0.6rem 0.75rem;
}
.cookie-guide__title { font-weight: 500; margin: 0 0 0.4rem; }
.cookie-guide__steps { margin: 0; padding-left: 1.2rem; line-height: 1.65; color: var(--text-muted); }
.cookie-guide__steps strong, .cookie-guide__steps em, .cookie-guide__steps code { color: var(--text); }
kbd {
  padding: 0.1rem 0.3rem;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  font-size: 0.75rem;
}

.cookie-input {
  width: 100%;
  box-sizing: border-box;
  padding: 0.45rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  color: var(--text);
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
  resize: vertical;
  outline: none;
}
.cookie-input:focus { border-color: var(--accent-blue); }
.cookie-input:disabled { opacity: 0.6; cursor: not-allowed; }

.status-error { font-size: 0.82rem; color: var(--status-error); margin: 0; }

.btn--sm { padding: 0.3rem 0.65rem; font-size: 0.8rem; align-self: flex-start; }

.slide-enter-active, .slide-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
