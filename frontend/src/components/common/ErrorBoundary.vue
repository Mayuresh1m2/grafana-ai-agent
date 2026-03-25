<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const error = ref<Error | null>(null)

onErrorCaptured((err) => {
  error.value = err instanceof Error ? err : new Error(String(err))
  return false // stop propagation
})

function reset() {
  error.value = null
}
</script>

<template>
  <div v-if="error" class="error-boundary" role="alert">
    <p class="error-boundary__title">Something went wrong</p>
    <pre class="error-boundary__msg">{{ error.message }}</pre>
    <button class="btn-secondary" @click="reset">Dismiss</button>
  </div>
  <slot v-else />
</template>

<style scoped>
.error-boundary {
  padding: 1.5rem;
  border: 1px solid var(--status-error);
  border-radius: var(--radius);
  background: rgba(255, 77, 106, 0.08);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.error-boundary__title {
  font-weight: 600;
  color: var(--status-error);
  margin: 0;
}

.error-boundary__msg {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--text-muted);
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
