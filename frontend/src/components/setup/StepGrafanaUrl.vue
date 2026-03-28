<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'

const session = useSessionStore()

const urlValid = computed(() => {
  try {
    const u = new URL(session.grafanaUrl)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
})

function next() {
  if (urlValid.value) session.goToStep(2)
}
</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Connect to Grafana</h2>
    <p class="step-panel__desc">Enter the base URL of your Grafana instance.</p>

    <label class="field-label" for="grafana-url">Grafana URL</label>
    <input
      id="grafana-url"
      v-model="session.grafanaUrl"
      type="url"
      class="field-input"
      :class="{ 'field-input--error': session.grafanaUrl && !urlValid }"
      placeholder="https://grafana.example.com"
      autocomplete="off"
      spellcheck="false"
      @keyup.enter="next"
    />
    <p v-if="session.grafanaUrl && !urlValid" class="field-error">
      Enter a valid http/https URL
    </p>

    <div class="step-panel__actions">
      <button class="btn-primary" :disabled="!urlValid" @click="next">
        Next
      </button>
    </div>
  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__actions { display: flex; gap: 0.75rem; margin-top: 0.5rem; }
.field-label { font-size: 0.85rem; font-weight: 500; color: var(--text-muted); }
.field-input {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  color: var(--text);
  font-size: 0.95rem;
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
}
.field-input:focus { border-color: var(--accent-blue); }
.field-input--error { border-color: var(--status-error); }
.field-error { font-size: 0.8rem; color: var(--status-error); margin: -0.5rem 0 0; }
</style>
