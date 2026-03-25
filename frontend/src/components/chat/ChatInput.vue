<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'

const props = defineProps<{
  isStreaming: boolean
  disabled?:   boolean
}>()

const emit = defineEmits<{
  (e: 'submit', query: string): void
  (e: 'stop'): void
}>()

const query     = ref('')
const textareaEl = ref<HTMLTextAreaElement | null>(null)

const canSubmit = computed(
  () => query.value.trim().length > 0 && !props.isStreaming && !props.disabled,
)

function autoResize() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

function submit() {
  const text = query.value.trim()
  if (!text || props.isStreaming || props.disabled) return
  emit('submit', text)
  query.value = ''
  nextTick(() => {
    autoResize()
    textareaEl.value?.focus()
  })
}
</script>

<template>
  <div class="chat-input">
    <textarea
      ref="textareaEl"
      v-model="query"
      class="chat-input__textarea"
      placeholder="Ask about your services…"
      rows="1"
      :disabled="disabled"
      @keydown="onKeydown"
      @input="autoResize"
    />

    <div class="chat-input__actions">
      <span class="chat-input__hint">Shift+Enter for newline</span>

      <button
        v-if="isStreaming"
        class="btn-secondary chat-input__stop"
        @click="emit('stop')"
        aria-label="Stop generation"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="8" height="8" rx="1" fill="currentColor"/>
        </svg>
        Stop
      </button>

      <button
        v-else
        class="btn-primary chat-input__send"
        :disabled="!canSubmit"
        @click="submit"
        aria-label="Send message"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M1.5 7h11M7.5 2l5.5 5-5.5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        Send
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-input {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border);
  background: var(--surface);
}

.chat-input__textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  color: var(--text);
  font-size: 0.95rem;
  font-family: var(--font-sans);
  line-height: 1.5;
  padding: 0.65rem 0.75rem;
  outline: none;
  transition: border-color 0.15s;
  min-height: 2.5rem;
  max-height: 200px;
  overflow-y: auto;
}
.chat-input__textarea:focus { border-color: var(--accent-blue); }
.chat-input__textarea:disabled { opacity: 0.5; cursor: not-allowed; }

.chat-input__actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  justify-content: flex-end;
}

.chat-input__hint {
  flex: 1;
  font-size: 0.72rem;
  color: var(--text-muted);
}

.chat-input__stop,
.chat-input__send {
  padding: 0.4rem 0.9rem;
  font-size: 0.82rem;
}
</style>
