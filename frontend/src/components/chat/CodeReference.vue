<script setup lang="ts">
import { ref, computed } from 'vue'
import type { CodeRefArtifact } from '@/types/chat'

const props = defineProps<{ artifact: CodeRefArtifact }>()

const copied = ref(false)

const vsCodeUrl = computed(() => {
  const path = props.artifact.repo_path
    ? `${props.artifact.repo_path}/${props.artifact.file_path}`
    : props.artifact.file_path
  return `vscode://file/${path}:${props.artifact.line_start}`
})

const displayPath = computed(() => {
  const parts = props.artifact.file_path.split('/')
  return parts.length > 3
    ? '…/' + parts.slice(-3).join('/')
    : props.artifact.file_path
})

const lineRange = computed(() =>
  props.artifact.line_start === props.artifact.line_end
    ? `L${props.artifact.line_start}`
    : `L${props.artifact.line_start}–${props.artifact.line_end}`,
)

async function copy() {
  await navigator.clipboard.writeText(props.artifact.snippet)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <div class="code-ref">
    <div class="code-ref__header">
      <a :href="vsCodeUrl" class="code-ref__path" title="Open in VS Code">
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden="true">
          <path d="M1.5 9.5L5 6.5l-3.5-3 1-1L7 6.5 2.5 10.5l-1-1z" fill="currentColor"/>
          <path d="M6 9.5L9.5 6.5l-3.5-3 1-1L11.5 6.5 7 10.5l-1-1z" fill="currentColor"/>
        </svg>
        {{ displayPath }}
      </a>
      <span class="code-ref__line">{{ lineRange }}</span>
      <span
        v-if="artifact.relevance_score != null"
        class="code-ref__score"
        :title="`Relevance: ${(artifact.relevance_score * 100).toFixed(0)}%`"
      >
        {{ (artifact.relevance_score * 100).toFixed(0) }}%
      </span>
      <button class="btn-ghost code-ref__copy" @click="copy">
        {{ copied ? 'Copied!' : 'Copy' }}
      </button>
    </div>
    <pre class="code-ref__snippet"><code>{{ artifact.snippet }}</code></pre>
  </div>
</template>

<style scoped>
.code-ref {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 0.78rem;
}

.code-ref__header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 0.75rem;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
  font-family: var(--font-sans);
  font-size: 0.78rem;
}

.code-ref__path {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex: 1;
  color: var(--accent-blue);
  text-decoration: underline;
  text-underline-offset: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.code-ref__path:hover { opacity: 0.8; }

.code-ref__line  { color: var(--text-muted); white-space: nowrap; }
.code-ref__score { color: var(--text-muted); white-space: nowrap; }

.code-ref__copy {
  padding: 0.15rem 0.4rem;
  font-size: 0.72rem;
  font-family: var(--font-sans);
  flex-shrink: 0;
}

.code-ref__snippet {
  padding: 0.75rem;
  background: var(--surface);
  color: var(--text);
  overflow-x: auto;
  white-space: pre;
  max-height: 220px;
  overflow-y: auto;
  line-height: 1.55;
  margin: 0;
}
</style>
