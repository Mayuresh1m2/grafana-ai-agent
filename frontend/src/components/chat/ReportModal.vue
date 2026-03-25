<script setup lang="ts">
import { computed, watch, nextTick, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useReportStore } from '@/stores/reportStore'

marked.setOptions({ gfm: true, breaks: false })

const emit  = defineEmits<{ (e: 'close'): void }>()
const report = useReportStore()

const scrollEl = ref<HTMLElement | null>(null)
const copied   = ref(false)

const html = computed(() => {
  if (!report.content) return ''
  return DOMPurify.sanitize(marked.parse(report.content) as string)
})

// Auto-scroll to bottom while streaming
watch(() => report.content, () => {
  if (report.isGenerating) nextTick(() => {
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  })
})

function close() {
  if (report.isGenerating) report.cancel()
  emit('close')
}

async function copyToClipboard() {
  await navigator.clipboard.writeText(report.content)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function downloadMarkdown() {
  const blob = new Blob([report.content], { type: 'text/markdown' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = `incident-report-${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function onOverlayClick(e: MouseEvent) {
  if (e.target === e.currentTarget) close()
}
</script>

<template>
  <Teleport to="body">
    <div class="modal-overlay" @click="onOverlayClick">
      <div class="modal" role="dialog" aria-modal="true" aria-label="Incident Report">

        <!-- Header -->
        <div class="modal__header">
          <div class="modal__title-row">
            <span class="modal__title">Incident Report</span>
            <span v-if="report.isGenerating" class="modal__generating">
              <span class="spinner" />
              Generating…
            </span>
          </div>

          <div class="modal__actions">
            <button
              class="btn-ghost btn--sm"
              :disabled="!report.isDone"
              :title="copied ? 'Copied!' : 'Copy Markdown'"
              @click="copyToClipboard"
            >
              {{ copied ? '✓ Copied' : 'Copy MD' }}
            </button>
            <button
              class="btn-ghost btn--sm"
              :disabled="!report.isDone"
              title="Download as .md"
              @click="downloadMarkdown"
            >
              Download .md
            </button>
            <button class="btn-ghost btn--sm modal__close" title="Close" @click="close">
              ✕
            </button>
          </div>
        </div>

        <!-- Error state -->
        <p v-if="report.error" class="modal__error">{{ report.error }}</p>

        <!-- Empty / generating placeholder -->
        <div v-else-if="!report.content" class="modal__placeholder">
          <span class="spinner spinner--lg" />
          <p>Analysing investigation transcript…</p>
        </div>

        <!-- Report content -->
        <div
          v-else
          ref="scrollEl"
          class="modal__body prose"
          v-html="html"
        />

      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1.5rem;
}

.modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  width: 100%;
  max-width: 780px;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
}

/* Header */
.modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.1rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  gap: 1rem;
}

.modal__title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.modal__title {
  font-size: 1rem;
  font-weight: 600;
}

.modal__generating {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: var(--text-muted);
}

.modal__actions {
  display: flex;
  gap: 0.4rem;
  flex-shrink: 0;
}

.modal__close {
  padding: 0.3rem 0.55rem;
  font-size: 0.9rem;
}

/* Body */
.modal__body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 1.5rem;
}

.modal__placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding: 3rem;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.modal__error {
  padding: 1rem 1.5rem;
  color: var(--status-error);
  font-size: 0.875rem;
}

/* Shared button size */
.btn--sm { padding: 0.3rem 0.65rem; font-size: 0.78rem; }

/* Spinners */
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent-blue);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}
.spinner--lg { width: 28px; height: 28px; border-width: 3px; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Prose styles for rendered Markdown */
.prose :deep(h2) {
  font-size: 1rem;
  font-weight: 700;
  margin: 1.4rem 0 0.4rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}
.prose :deep(h2:first-child) { margin-top: 0; }
.prose :deep(p)  { font-size: 0.875rem; line-height: 1.65; margin: 0.5rem 0; color: var(--text); }
.prose :deep(ul),
.prose :deep(ol) { font-size: 0.875rem; line-height: 1.65; padding-left: 1.4rem; margin: 0.4rem 0; color: var(--text); }
.prose :deep(li) { margin: 0.2rem 0; }
.prose :deep(code) {
  font-family: var(--font-mono, monospace);
  font-size: 0.8rem;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0.1rem 0.35rem;
}
.prose :deep(pre) {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.75rem 1rem;
  overflow-x: auto;
  margin: 0.6rem 0;
}
.prose :deep(pre code) { background: none; border: none; padding: 0; }
.prose :deep(blockquote) {
  border-left: 3px solid var(--accent-blue);
  margin: 0.5rem 0;
  padding: 0.25rem 0.75rem;
  color: var(--text-muted);
}
.prose :deep(input[type="checkbox"]) { margin-right: 0.4rem; }
</style>
