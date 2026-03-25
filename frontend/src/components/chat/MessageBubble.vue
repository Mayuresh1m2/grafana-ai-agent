<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { ChatMessage } from '@/types/chat'
import ThinkingBubble from './ThinkingBubble.vue'
import LogSnippet     from './LogSnippet.vue'
import MetricCard     from './MetricCard.vue'
import CodeReference  from './CodeReference.vue'

const props = defineProps<{ message: ChatMessage }>()

// Configure marked once (at module level in production, but here for simplicity)
marked.setOptions({ gfm: true, breaks: false })

const htmlContent = computed(() => {
  if (props.message.role !== 'assistant') return ''
  const raw = marked.parse(props.message.content) as string
  return DOMPurify.sanitize(raw)
})

function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div
    class="message-bubble"
    :class="[`message-bubble--${message.role}`, `message-bubble--${message.status}`]"
  >
    <!-- User message -->
    <template v-if="message.role === 'user'">
      <div class="message-bubble__user-content">{{ message.content }}</div>
      <span class="message-bubble__time">{{ formatTime(message.timestamp) }}</span>
    </template>

    <!-- Assistant message -->
    <template v-else>
      <!-- Thinking section -->
      <ThinkingBubble
        v-if="message.thinking"
        :thinking="message.thinking"
        class="message-bubble__thinking"
      />

      <!-- Tool calls -->
      <div v-if="message.toolCalls.length" class="message-bubble__tools">
        <div
          v-for="(tc, i) in message.toolCalls"
          :key="i"
          class="tool-call"
          :class="tc.summary ? (tc.had_data ? 'tool-call--ok' : 'tool-call--empty') : 'tool-call--pending'"
        >
          <span class="tool-call__icon" aria-hidden="true">
            <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
              <path d="M2 5.5h7M6.5 3l2.5 2.5L6.5 8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </span>
          <span class="tool-call__name">{{ tc.tool }}</span>
          <span v-if="tc.summary" class="tool-call__summary">{{ tc.summary }}</span>
          <span v-else class="tool-call__pending">running…</span>
        </div>
      </div>

      <!-- Streaming dots while content is empty -->
      <div v-if="message.status === 'streaming' && !message.content" class="message-bubble__dots">
        <span /><span /><span />
      </div>

      <!-- Markdown content -->
      <div
        v-if="message.content"
        class="message-bubble__content prose"
        v-html="htmlContent"
      />

      <!-- Artifacts -->
      <div v-if="message.artifacts.length" class="message-bubble__artifacts">
        <template v-for="(artifact, i) in message.artifacts" :key="i">
          <LogSnippet    v-if="artifact.kind === 'log'"      :artifact="artifact" />
          <MetricCard    v-if="artifact.kind === 'metric'"   :artifact="artifact" />
          <CodeReference v-if="artifact.kind === 'code_ref'" :artifact="artifact" />
        </template>
      </div>

      <!-- Error state -->
      <div v-if="message.status === 'error'" class="message-bubble__error">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.3"/>
          <path d="M7 4v3.5M7 9.5h.01" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
        </svg>
        {{ message.errorMessage ?? 'An error occurred' }}
      </div>

      <span class="message-bubble__time">{{ formatTime(message.timestamp) }}</span>
    </template>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  max-width: 80%;
  padding: 0.75rem 1rem;
  border-radius: calc(var(--radius) * 1.5);
  position: relative;
}

/* User */
.message-bubble--user {
  align-self: flex-end;
  background: var(--accent-blue);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-bubble__user-content {
  font-size: 0.95rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Assistant */
.message-bubble--assistant {
  align-self: flex-start;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  max-width: 90%;
}

.message-bubble--error {
  border-color: rgba(255, 77, 106, 0.4);
}

.message-bubble__thinking {
  margin-bottom: 0.25rem;
}

/* Tool calls */
.message-bubble__tools {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.tool-call {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  border-radius: var(--radius-sm, 4px);
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-muted);
}
.tool-call--ok      { border-color: rgba(80, 200, 120, 0.35); color: var(--text); }
.tool-call--empty   { border-color: var(--border); }
.tool-call--pending { opacity: 0.7; }
.tool-call__icon    { flex-shrink: 0; display: flex; align-items: center; }
.tool-call--ok .tool-call__icon    { color: var(--status-ok, #50c878); }
.tool-call--empty .tool-call__icon { color: var(--text-muted); }
.tool-call__name    { font-family: var(--font-mono, monospace); font-weight: 500; white-space: nowrap; }
.tool-call__summary { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); }
.tool-call__pending { font-style: italic; color: var(--text-muted); }

.message-bubble__content { font-size: 0.9rem; }

.message-bubble__artifacts {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.message-bubble__error {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  color: var(--status-error);
  padding: 0.4rem 0.6rem;
  background: rgba(255, 77, 106, 0.08);
  border-radius: var(--radius-sm);
}

.message-bubble__time {
  font-size: 0.7rem;
  color: rgba(255,255,255,0.5);
  align-self: flex-end;
}
.message-bubble--assistant .message-bubble__time {
  color: var(--text-muted);
}

/* Typing dots */
.message-bubble__dots {
  display: flex;
  gap: 5px;
  padding: 4px 0;
}
.message-bubble__dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: dot-bounce 1.2s ease-in-out infinite;
}
.message-bubble__dots span:nth-child(2) { animation-delay: 0.2s; }
.message-bubble__dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40%            { transform: translateY(-5px); opacity: 1; }
}
</style>
