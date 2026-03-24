<script setup lang="ts">
import { ref } from 'vue'
import { useAgentStore } from '@/stores'
import AgentChat from '@/components/AgentChat.vue'
import ModelSelector from '@/components/ModelSelector.vue'

const agentStore = useAgentStore()
const inputQuery = ref('')

async function handleSubmit(): Promise<void> {
  const query = inputQuery.value.trim()
  if (!query || agentStore.isLoading) return
  inputQuery.value = ''
  await agentStore.sendQuery(query)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void handleSubmit()
  }
}
</script>

<template>
  <div class="chat-view">
    <div class="chat-toolbar">
      <ModelSelector />
      <button
        class="clear-btn"
        :disabled="!agentStore.hasMessages"
        title="Clear conversation"
        @click="agentStore.clearMessages()"
      >
        Clear
      </button>
    </div>

    <AgentChat :messages="agentStore.messages" :is-loading="agentStore.isLoading" />

    <div v-if="agentStore.error" role="alert" class="error-banner">
      {{ agentStore.error }}
    </div>

    <form class="input-row" @submit.prevent="handleSubmit">
      <textarea
        v-model="inputQuery"
        class="query-input"
        placeholder="Ask about your metrics, logs, or traces… (Enter to send, Shift+Enter for newline)"
        rows="2"
        :disabled="agentStore.isLoading"
        aria-label="Query input"
        @keydown="handleKeydown"
      />
      <button type="submit" class="send-btn" :disabled="agentStore.isLoading || !inputQuery.trim()">
        {{ agentStore.isLoading ? 'Thinking…' : 'Send' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 96px);
  gap: 0.75rem;
}

.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  justify-content: flex-end;
}

.clear-btn {
  padding: 0.35rem 0.9rem;
  background: transparent;
  color: #9ca3af;
  border: 1px solid #374151;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: color 0.15s, border-color 0.15s;
}

.clear-btn:hover:not(:disabled) {
  color: #f3f4f6;
  border-color: #6b7280;
}

.clear-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.error-banner {
  padding: 0.6rem 1rem;
  background: #7f1d1d;
  color: #fecaca;
  border-radius: 6px;
  font-size: 0.875rem;
}

.input-row {
  display: flex;
  gap: 0.75rem;
  align-items: flex-end;
}

.query-input {
  flex: 1;
  padding: 0.65rem 1rem;
  border: 1px solid #374151;
  border-radius: 8px;
  background: #1f2937;
  color: #f3f4f6;
  font-size: 0.9rem;
  font-family: inherit;
  resize: none;
  line-height: 1.5;
  transition: border-color 0.15s;
}

.query-input:focus {
  outline: none;
  border-color: #f97316;
}

.query-input:disabled {
  opacity: 0.6;
}

.send-btn {
  padding: 0.65rem 1.5rem;
  background: #f97316;
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9rem;
  white-space: nowrap;
  transition: background 0.15s;
  align-self: flex-end;
}

.send-btn:hover:not(:disabled) {
  background: #ea6c0a;
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
