<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useSessionStore } from '@/stores/sessionStore'

const session = useSessionStore()
const router  = useRouter()

function reconnect() {
  // Return to the Authenticate step so the user can log in again with any method
  session.goToStep(2)
  router.push('/setup')
}
</script>

<template>
  <div class="expired-banner">
    <span class="expired-banner__icon" aria-hidden="true">⚠</span>
    <span class="expired-banner__msg">
      Grafana session expired or was lost. Please re-authenticate to continue.
    </span>
    <button class="btn-primary btn--sm" @click="reconnect">
      Reconnect to Grafana
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
