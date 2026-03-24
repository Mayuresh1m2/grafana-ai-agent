<script setup lang="ts">
import { useAgentStore } from '@/stores'

const agentStore = useAgentStore()

const MODELS: string[] = ['llama3', 'llama3:8b', 'mistral', 'phi3', 'gemma2']
</script>

<template>
  <label class="model-selector" for="model-select">
    <span class="label-text">Model</span>
    <select
      id="model-select"
      :value="agentStore.selectedModel"
      class="select"
      @change="agentStore.setModel(($event.target as HTMLSelectElement).value)"
    >
      <option v-for="model in MODELS" :key="model" :value="model">
        {{ model }}
      </option>
    </select>
  </label>
</template>

<style scoped>
.model-selector {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
}

.label-text {
  color: #6b7280;
}

.select {
  background: #1f2937;
  color: #e5e7eb;
  border: 1px solid #374151;
  border-radius: 6px;
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
  cursor: pointer;
}

.select:focus {
  outline: none;
  border-color: #f97316;
}
</style>
