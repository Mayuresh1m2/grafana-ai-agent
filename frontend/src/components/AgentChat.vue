<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '@/types/agent'

const props = defineProps<{
  messages: ChatMessage[]
  isLoading: boolean
}>()

const scrollRef = ref<HTMLElement | null>(null)

watch(
  () => props.messages.length,
  async () => {
    await nextTick()
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    }
  },
)

function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div ref="scrollRef" class="chat-messages" role="log" aria-live="polite" aria-label="Chat messages">
    <div v-if="messages.length === 0 && !isLoading" class="empty-state">
      <p>Ask a question about your Grafana dashboards, Loki logs, or Prometheus metrics.</p>
      <p class="empty-hint">e.g. "What is the p99 latency of the checkout service?"</p>
    </div>

    <article
      v-for="msg in messages"
      :key="msg.id"
      :class="['message', `message--${msg.role}`]"
    >
      <header class="message-header">
        <span class="message-role">{{ msg.role === 'user' ? 'You' : 'Agent' }}</span>
        <time class="message-time" :datetime="msg.timestamp.toISOString()">
          {{ formatTime(msg.timestamp) }}
        </time>
      </header>
      <p class="message-content">{{ msg.content }}</p>
    </article>

    <div v-if="isLoading" class="message message--assistant loading" aria-label="Agent is thinking">
      <header class="message-header">
        <span class="message-role">Agent</span>
      </header>
      <p class="message-content">
        <span class="dot" />
        <span class="dot" />
        <span class="dot" />
      </p>
    </div>
  </div>
</template>

<style scoped>
.chat-messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-right: 0.25rem;
}

.empty-state {
  color: #6b7280;
  text-align: center;
  margin: auto 0;
  padding: 2rem;
}

.empty-hint {
  font-size: 0.8rem;
  margin-top: 0.4rem;
  color: #4b5563;
  font-style: italic;
}

.message {
  padding: 0.75rem 1rem;
  border-radius: 10px;
  max-width: 88%;
  word-break: break-word;
}

.message--user {
  background: #1e3a5f;
  align-self: flex-end;
  border-bottom-right-radius: 3px;
}

.message--assistant {
  background: #1f2937;
  border: 1px solid #374151;
  align-self: flex-start;
  border-bottom-left-radius: 3px;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.3rem;
}

.message-role {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #6b7280;
}

.message-time {
  font-size: 0.7rem;
  color: #4b5563;
}

.message-content {
  margin: 0;
  white-space: pre-wrap;
  font-size: 0.9rem;
  line-height: 1.65;
}

/* Typing indicator dots */
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #6b7280;
  margin-right: 4px;
  animation: bounce 1.2s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}
</style>
