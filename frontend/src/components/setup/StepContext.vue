<script setup lang="ts">
import { ref, computed } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import type { Environment } from '@/types/chat'

const session = useSessionStore()

const serviceInput = ref('')
const envOptions: { value: Environment; label: string }[] = [
  { value: 'prod',    label: 'Production' },
  { value: 'staging', label: 'Staging' },
  { value: 'dev',     label: 'Development' },
  { value: 'custom',  label: 'Custom' },
]

const canProceed = computed(() => !!session.namespace.trim())

function addService() {
  const val = serviceInput.value.trim()
  if (val) {
    session.addService(val)
    serviceInput.value = ''
  }
}

function onServiceKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    addService()
  }
}

function back() { session.goToStep(2) }
function next() { if (canProceed.value) session.goToStep(4) }
</script>

<template>
  <div class="step-panel">
    <h2 class="step-panel__title">Context</h2>
    <p class="step-panel__desc">Set your Kubernetes namespace, environment, monitored services, and optional repo path.</p>

    <div class="field-group">
      <label class="field-label" for="namespace">Namespace <span class="required">*</span></label>
      <input
        id="namespace"
        v-model="session.namespace"
        type="text"
        class="field-input"
        placeholder="e.g. production"
      />
    </div>

    <div class="field-group">
      <label class="field-label">Environment</label>
      <div class="env-options">
        <label
          v-for="opt in envOptions"
          :key="opt.value"
          class="env-option"
          :class="{ 'env-option--active': session.environment === opt.value }"
        >
          <input
            type="radio"
            :value="opt.value"
            v-model="session.environment"
            class="sr-only"
          />
          {{ opt.label }}
        </label>
      </div>
    </div>

    <div class="field-group">
      <label class="field-label" for="service-input">Services</label>
      <div class="tag-input">
        <span
          v-for="svc in session.services"
          :key="svc"
          class="tag"
        >
          {{ svc }}
          <button class="tag__remove" @click="session.removeService(svc)" aria-label="Remove">×</button>
        </span>
        <input
          id="service-input"
          v-model="serviceInput"
          type="text"
          class="tag-input__field"
          placeholder="Type and press Enter"
          @keydown="onServiceKeydown"
          @blur="addService"
        />
      </div>
    </div>

    <div class="field-group">
      <label class="field-label" for="repo-path">Repo path <span class="optional">(optional)</span></label>
      <input
        id="repo-path"
        v-model="session.repoPath"
        type="text"
        class="field-input"
        placeholder="/path/to/your/repo"
      />
    </div>

    <div class="step-panel__nav">
      <button class="btn-ghost" @click="back">Back</button>
      <button class="btn-primary" :disabled="!canProceed" @click="next">Next</button>
    </div>
  </div>
</template>

<style scoped>
.step-panel { display: flex; flex-direction: column; gap: 1.25rem; }
.step-panel__title { font-size: 1.25rem; font-weight: 600; margin: 0; }
.step-panel__desc  { color: var(--text-muted); font-size: 0.9rem; margin: 0; }
.step-panel__nav   { display: flex; gap: 0.75rem; margin-top: 0.5rem; }

.field-group { display: flex; flex-direction: column; gap: 0.4rem; }
.field-label  { font-size: 0.85rem; font-weight: 500; color: var(--text-muted); }
.required { color: var(--status-error); }
.optional { font-weight: 400; opacity: 0.6; }
.field-input {
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

.env-options { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.env-option {
  padding: 0.35rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 2rem;
  font-size: 0.85rem;
  cursor: pointer;
  user-select: none;
  color: var(--text-muted);
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.env-option--active {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
  background: rgba(74,158,255,0.1);
}

.tag-input {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  min-height: 2.5rem;
  align-items: center;
  transition: border-color 0.15s;
  cursor: text;
}
.tag-input:focus-within { border-color: var(--accent-blue); }

.tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.15rem 0.5rem;
  background: rgba(74,158,255,0.15);
  border: 1px solid rgba(74,158,255,0.3);
  border-radius: 3px;
  font-size: 0.8rem;
  color: var(--accent-blue);
}
.tag__remove {
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  font-size: 1rem;
  line-height: 1;
  padding: 0;
  opacity: 0.7;
}
.tag__remove:hover { opacity: 1; }

.tag-input__field {
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 0.9rem;
  flex: 1;
  min-width: 8rem;
}

.sr-only {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0,0,0,0); border: 0;
}
</style>
