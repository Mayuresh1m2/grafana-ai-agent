<script setup lang="ts">
/**
 * ThinkingBubble — RAF-based typewriter for streaming "thinking" chunks.
 *
 * Strategy:
 *  - fullText = chunks.join('')          (source of truth, grows as SSE arrives)
 *  - displayText                          (what is shown, lags behind)
 *  - A single RAF loop drains the lag at CHARS_PER_FRAME chars/frame (~180 cps @ 60fps)
 *  - When isDone and displayText catches up, the cursor blink stops
 *  - Collapse/expand toggles the content area
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import type { ThinkingState } from '@/types/chat'

const CHARS_PER_FRAME = 3

const props = defineProps<{ thinking: ThinkingState }>()

const displayText = ref('')
let rafId: number | null = null

const fullText = computed(() => props.thinking.chunks.join(''))

function drain() {
  const full = fullText.value
  if (displayText.value.length < full.length) {
    displayText.value = full.slice(
      0,
      Math.min(displayText.value.length + CHARS_PER_FRAME, full.length),
    )
  }
  // Keep looping if there's more to render, or if not yet done (new chunks may arrive)
  if (displayText.value.length < full.length || !props.thinking.isDone) {
    rafId = requestAnimationFrame(drain)
  } else {
    rafId = null
  }
}

function startDrain() {
  if (rafId === null) rafId = requestAnimationFrame(drain)
}

// Re-arm whenever chunks grow
watch(
  () => props.thinking.chunks.length,
  () => startDrain(),
  { immediate: true },
)

// When done, do one final drain pass to ensure all text is displayed
watch(
  () => props.thinking.isDone,
  (done) => { if (done) startDrain() },
)

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
})

const isCursorActive = computed(
  () => !props.thinking.isDone || displayText.value.length < fullText.value.length,
)

function toggle() {
  props.thinking.collapsed = !props.thinking.collapsed
}
</script>

<template>
  <div class="thinking-bubble" :class="{ 'thinking-bubble--done': thinking.isDone }">
    <button class="thinking-bubble__header" @click="toggle" :aria-expanded="!thinking.collapsed">
      <span class="thinking-bubble__icon" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.2"/>
          <path d="M5 5.5a2 2 0 0 1 4 0c0 1.2-.8 1.6-1.5 2.2V9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
          <circle cx="7" cy="11" r="0.6" fill="currentColor"/>
        </svg>
      </span>
      <span class="thinking-bubble__label">
        {{ thinking.isDone ? 'Thought process' : 'Thinking…' }}
      </span>
      <span class="thinking-bubble__chevron" :class="{ 'thinking-bubble__chevron--open': !thinking.collapsed }">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M3 4.5l3 3 3-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>
    </button>

    <Transition name="thinking-expand">
      <div v-show="!thinking.collapsed" class="thinking-bubble__body">
        <pre class="thinking-bubble__text"
          >{{ displayText }}<span v-if="isCursorActive" class="thinking-bubble__cursor" aria-hidden="true">▋</span></pre>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.thinking-bubble {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  overflow: hidden;
  font-size: 0.85rem;
}

.thinking-bubble__header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.55rem 0.75rem;
  background: none;
  border: none;
  color: var(--thinking-color, #a78bfa);
  cursor: pointer;
  text-align: left;
  font-size: 0.82rem;
  font-weight: 500;
}
.thinking-bubble__header:hover { background: var(--surface-3); }

.thinking-bubble__icon { display: flex; align-items: center; color: var(--thinking-color, #a78bfa); }
.thinking-bubble__label { flex: 1; }

.thinking-bubble__chevron {
  display: flex;
  align-items: center;
  color: var(--text-muted);
  transition: transform 0.2s;
}
.thinking-bubble__chevron--open { transform: rotate(180deg); }

.thinking-bubble__body {
  border-top: 1px solid var(--border);
  padding: 0.75rem;
  max-height: 280px;
  overflow-y: auto;
}

.thinking-bubble__text {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  line-height: 1.6;
  color: var(--text-muted);
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

.thinking-bubble__cursor {
  display: inline-block;
  color: var(--thinking-color, #a78bfa);
  animation: blink 1s step-end infinite;
  margin-left: 1px;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}

/* Expand/collapse transition */
.thinking-expand-enter-active,
.thinking-expand-leave-active {
  transition: max-height 0.2s ease, opacity 0.2s ease;
  overflow: hidden;
}
.thinking-expand-enter-from,
.thinking-expand-leave-to {
  max-height: 0;
  opacity: 0;
}
.thinking-expand-enter-to,
.thinking-expand-leave-from {
  max-height: 280px;
  opacity: 1;
}
</style>
