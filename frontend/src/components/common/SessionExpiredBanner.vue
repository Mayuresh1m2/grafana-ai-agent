<script setup lang="ts">
import { ref } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import { reauthSsoBrowser } from '@/api/session'

const emit = defineEmits<{ (e: 'refreshed'): void }>()

const session    = useSessionStore()
const refreshing = ref(false)
const error      = ref<string | null>(null)

async function reauth() {
  if (!session.sessionId) return
  error.value    = null
  refreshing.value = true
  try {
    await reauthSsoBrowser(session.sessionId)
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
    <span class="expired-banner__icon" aria-hidden="true">⚠</span>
    <span class="expired-banner__msg">
      {{ refreshing ? 'Browser window opened — complete your Microsoft SSO login to continue.' : 'Grafana session expired.' }}
    </span>
    <p v-if="error" class="expired-banner__error">{{ error }}</p>
    <button class="btn-primary btn--sm" :disabled="refreshing" @click="reauth">
      {{ refreshing ? 'Waiting for login…' : 'Re-authenticate' }}
    </button>
  </div>
</template>

<style scoped>
.expired-banner {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  background: color-mix(in srgb, var(--status-warning, #f59e0b) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--status-warning, #f59e0b) 40%, transparent);
  border-radius: var(--radius);
  padding: 0.6rem 0.9rem;
  margin: 0.5rem 1rem;
}

.expired-banner__icon  { font-size: 0.9rem; flex-shrink: 0; }
.expired-banner__msg   { flex: 1; font-size: 0.875rem; min-width: 180px; }
.expired-banner__error { width: 100%; font-size: 0.82rem; color: var(--status-error); margin: 0; }

.btn--sm { padding: 0.3rem 0.65rem; font-size: 0.8rem; white-space: nowrap; flex-shrink: 0; }
</style>
