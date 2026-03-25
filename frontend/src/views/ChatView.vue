<script setup lang="ts">
import { ref, watch, nextTick, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '@/stores/sessionStore'
import { useChatStore }    from '@/stores/chatStore'
import Sidebar              from '@/components/chat/Sidebar.vue'
import MessageBubble        from '@/components/chat/MessageBubble.vue'
import ChatInput            from '@/components/chat/ChatInput.vue'
import ReportModal          from '@/components/chat/ReportModal.vue'
import ErrorBoundary        from '@/components/common/ErrorBoundary.vue'
import SessionExpiredBanner from '@/components/common/SessionExpiredBanner.vue'
import { useReportStore }   from '@/stores/reportStore'

const router  = useRouter()
const session = useSessionStore()
const chat    = useChatStore()
const report  = useReportStore()

const showReport = ref(false)

function openReport() {
  report.reset()
  showReport.value = true
  report.generate(chat.messages, {
    environment:  session.environment,
    namespace:    session.namespace,
    services:     session.services.join(', '),
    grafana_url:  session.grafanaUrl,
    active_alerts: session.alerts.length
      ? session.alerts.map((a) => `[${a.severity.toUpperCase()}] ${a.name}`).join(', ')
      : 'none',
  })
}

const scrollEl = ref<HTMLElement | null>(null)

// Guard: redirect to setup if not ready; then fetch active alerts
onMounted(() => {
  if (!session.setupComplete) { router.replace('/setup'); return }
  session.loadAlerts()
})

function alertsContext(): string {
  if (session.alertsLoading) return 'Loading active alerts…'
  if (!session.alerts.length) return 'No active alerts'
  return session.alerts
    .map((a) => {
      const svc = a.labels['service'] ?? a.labels['job'] ?? ''
      const svcStr = svc ? ` (${svc})` : ''
      const summary = a.summary ? ` — ${a.summary}` : ''
      return `[${a.severity.toUpperCase()}] ${a.name}${svcStr}${summary}`
    })
    .join('; ')
}

function sessionPayload() {
  return {
    session_id:     session.sessionId,
    grafana_url:    session.grafanaUrl,
    namespace:      session.namespace,
    environment:    session.environment,
    services:       session.services,
    repo_path:      session.repoPath,
    active_alerts:  alertsContext(),
  }
}

function sendQuery(query: string) {
  chat.sendQuery(query, sessionPayload())
}

function handleQuickAction(q: string) {
  sendQuery(q)
}

// Auto-scroll to bottom when messages change
watch(
  () => chat.messages.length,
  () => nextTick(scrollToBottom),
)

// Also scroll while streaming content grows
watch(
  () => chat.messages.at(-1)?.content,
  () => { if (chat.isStreaming) nextTick(scrollToBottom) },
)

function scrollToBottom() {
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

const suggestions = computed<string[]>(() => {
  if (chat.isStreaming) return []
  const last = chat.messages.at(-1)
  return (last?.role === 'assistant' && last.status === 'complete') ? last.suggestions : []
})
</script>

<template>
  <div class="chat-view">
    <Sidebar
      class="chat-view__sidebar"
      @quick-action="handleQuickAction"
      @generate-report="openReport"
    />

    <div class="chat-view__main">
      <ErrorBoundary>
        <!-- Session-expired banner -->
        <SessionExpiredBanner
          v-if="chat.sessionExpired"
          @refreshed="chat.sessionExpired = false"
        />

        <!-- Message thread -->
        <div ref="scrollEl" class="chat-view__thread">
          <div v-if="!chat.hasMessages" class="chat-view__empty">
            <p class="chat-view__empty-title">OnCall AI</p>
            <p class="chat-view__empty-sub">
              Ask about your services, metrics, or logs. I have access to
              <strong>{{ session.namespace }}</strong> in
              <strong>{{ session.environment }}</strong>.
            </p>
          </div>

          <TransitionGroup name="msg" tag="div" class="chat-view__messages">
            <MessageBubble
              v-for="msg in chat.messages"
              :key="msg.id"
              :message="msg"
            />
          </TransitionGroup>
        </div>

        <!-- Suggestion chips -->
        <Transition name="chips">
          <div v-if="suggestions.length" class="suggestions">
            <button
              v-for="s in suggestions"
              :key="s"
              class="suggestion-chip"
              @click="sendQuery(s)"
            >
              {{ s }}
            </button>
          </div>
        </Transition>

        <!-- Input bar -->
        <ChatInput
          :is-streaming="chat.isStreaming"
          @submit="sendQuery"
          @stop="chat.stopStream"
        />
      </ErrorBoundary>
    </div>
  </div>

  <!-- Report modal -->
  <ReportModal v-if="showReport" @close="showReport = false" />
</template>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.chat-view__main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.chat-view__thread {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0;
  scroll-behavior: smooth;
}

.chat-view__messages {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.chat-view__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 0.75rem;
  padding: 2rem;
  color: var(--text-muted);
}

.chat-view__empty-title {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text);
}

.chat-view__empty-sub {
  font-size: 0.9rem;
  max-width: 400px;
  line-height: 1.6;
}

/* Message enter animation */
.msg-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.msg-enter-from   { opacity: 0; transform: translateY(8px); }

/* Suggestion chips */
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border);
}

.suggestion-chip {
  padding: 0.35rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 9999px;
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  white-space: nowrap;
}
.suggestion-chip:hover {
  background: var(--surface-3, var(--surface-2));
  color: var(--text);
  border-color: var(--accent-blue);
}

.chips-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.chips-leave-active { transition: opacity 0.1s ease; }
.chips-enter-from   { opacity: 0; transform: translateY(4px); }
.chips-leave-to     { opacity: 0; }
</style>
