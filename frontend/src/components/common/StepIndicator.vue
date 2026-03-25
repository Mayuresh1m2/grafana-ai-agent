<script setup lang="ts">
import type { SetupStep } from '@/types/chat'

const props = defineProps<{
  current: SetupStep
  steps: { label: string }[]
}>()
</script>

<template>
  <nav class="step-indicator" aria-label="Setup progress">
    <div
      v-for="(step, i) in steps"
      :key="i"
      class="step"
      :class="{
        'step--done':    i + 1 < current,
        'step--active':  i + 1 === current,
        'step--pending': i + 1 > current,
      }"
    >
      <span class="step__circle">
        <svg v-if="i + 1 < current" width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2 6l3 3 5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span v-else>{{ i + 1 }}</span>
      </span>
      <span class="step__label">{{ step.label }}</span>
      <span v-if="i < steps.length - 1" class="step__connector" aria-hidden="true" />
    </div>
  </nav>
</template>

<style scoped>
.step-indicator {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0 1rem;
}

.step {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.step__circle {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
  border: 2px solid var(--border);
  color: var(--text-muted);
  background: var(--surface-2);
}

.step--done .step__circle {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
  color: #fff;
}

.step--active .step__circle {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
  background: transparent;
}

.step__label {
  font-size: 0.8rem;
  color: var(--text-muted);
  white-space: nowrap;
}

.step--active .step__label {
  color: var(--text);
  font-weight: 500;
}

.step--done .step__label {
  color: var(--text-muted);
}

.step__connector {
  display: block;
  width: 2rem;
  height: 1px;
  background: var(--border);
  margin: 0 0.5rem;
  flex-shrink: 0;
}
</style>
