import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useLocalStorage } from '@/composables/useLocalStorage'
import { fetchAlerts } from '@/api/session'
import type { AlertInfo } from '@/api/session'
import type { SetupStep, Environment, AuthStatus, SessionConfig } from '@/types/chat'

export const useSessionStore = defineStore('session', () => {
  // ── Persisted state ──────────────────────────────────────────────────────
  const step         = useLocalStorage<SetupStep>('setup.step', 1)
  const grafanaUrl   = useLocalStorage<string>('setup.grafanaUrl', '')
  const namespace    = useLocalStorage<string>('setup.namespace', '')
  const environment  = useLocalStorage<Environment>('setup.environment', 'prod')
  const services     = useLocalStorage<string[]>('setup.services', [])
  const repoPath     = useLocalStorage<string>('setup.repoPath', '')
  const sessionId    = useLocalStorage<string | null>('setup.sessionId', null)

  // ── Transient state ──────────────────────────────────────────────────────
  const authStatus    = ref<AuthStatus>('idle')
  const authPollTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const setupComplete = ref(false)
  const alerts            = ref<AlertInfo[]>([])
  const alertsLoading     = ref(false)

  // ── Computed ─────────────────────────────────────────────────────────────
  const config = computed<SessionConfig>(() => ({
    grafanaUrl:  grafanaUrl.value,
    namespace:   namespace.value,
    environment: environment.value,
    services:    services.value,
    repoPath:    repoPath.value,
    sessionId:   sessionId.value,
  }))

  const isReady = computed(() =>
    setupComplete.value &&
    !!grafanaUrl.value &&
    !!namespace.value &&
    authStatus.value === 'complete'
  )

  // ── Actions ──────────────────────────────────────────────────────────────
  function goToStep(s: SetupStep) { step.value = s }

  function startAuthPoll(pollFn: () => Promise<AuthStatus>) {
    stopAuthPoll()
    authStatus.value = 'pending'
    authPollTimer.value = setInterval(async () => {
      const status = await pollFn()
      authStatus.value = status
      if (status === 'complete' || status === 'failed') stopAuthPoll()
    }, 2000)
  }

  function stopAuthPoll() {
    if (authPollTimer.value) {
      clearInterval(authPollTimer.value)
      authPollTimer.value = null
    }
  }

  function confirmSetup() {
    setupComplete.value = true
    // Keep the sessionId already set during the Grafana connect call — do not overwrite it
    if (!sessionId.value) sessionId.value = `session_${Date.now()}`
  }

  function resetSetup() {
    step.value         = 1
    grafanaUrl.value   = ''
    namespace.value    = ''
    environment.value  = 'prod'
    services.value     = []
    repoPath.value     = ''
    sessionId.value    = null
    authStatus.value   = 'idle'
    setupComplete.value = false
    stopAuthPoll()
  }

  async function loadAlerts() {
    if (!sessionId.value) return
    alertsLoading.value = true
    try {
      alerts.value = await fetchAlerts(sessionId.value)
    } catch {
      alerts.value = []
    } finally {
      alertsLoading.value = false
    }
  }

  function addService(svc: string) {
    const trimmed = svc.trim()
    if (trimmed && !services.value.includes(trimmed)) {
      services.value = [...services.value, trimmed]
    }
  }

  function removeService(svc: string) {
    services.value = services.value.filter((s) => s !== svc)
  }

  return {
    // state
    step, grafanaUrl, namespace, environment, services, repoPath, sessionId,
    authStatus, setupComplete, alerts, alertsLoading,
    // computed
    config, isReady,
    // actions
    goToStep, startAuthPoll, stopAuthPoll,
    confirmSetup, resetSetup, addService, removeService, loadAlerts,
  }
})
