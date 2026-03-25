<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '@/stores/sessionStore'
import StepIndicator  from '@/components/common/StepIndicator.vue'
import ErrorBoundary  from '@/components/common/ErrorBoundary.vue'
import StepGrafanaUrl from '@/components/setup/StepGrafanaUrl.vue'
import StepAuth       from '@/components/setup/StepAuth.vue'
import StepContext    from '@/components/setup/StepContext.vue'
import StepConfirm    from '@/components/setup/StepConfirm.vue'

const session = useSessionStore()

const steps = [
  { label: 'Connect' },
  { label: 'Authenticate' },
  { label: 'Context' },
  { label: 'Confirm' },
]

const currentComponent = computed(() => {
  switch (session.step) {
    case 1: return StepGrafanaUrl
    case 2: return StepAuth
    case 3: return StepContext
    case 4: return StepConfirm
    default: return StepGrafanaUrl
  }
})
</script>

<template>
  <div class="setup-view">
    <div class="setup-card">
      <header class="setup-card__header">
        <h1 class="setup-card__brand">OnCall AI</h1>
        <p class="setup-card__sub">Let's connect to your Grafana instance</p>
      </header>

      <StepIndicator :current="session.step" :steps="steps" class="setup-card__steps" />

      <main class="setup-card__body">
        <ErrorBoundary>
          <Transition name="slide-up" mode="out-in">
            <component :is="currentComponent" :key="session.step" />
          </Transition>
        </ErrorBoundary>
      </main>
    </div>
  </div>
</template>

<style scoped>
.setup-view {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem 1rem;
  background: var(--bg);
}

.setup-card {
  width: 100%;
  max-width: 540px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: calc(var(--radius) * 2);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.setup-card__header {
  padding: 2rem 2rem 1.5rem;
  border-bottom: 1px solid var(--border);
}

.setup-card__brand {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--accent-blue);
  margin: 0 0 0.25rem;
}

.setup-card__sub {
  color: var(--text-muted);
  font-size: 0.9rem;
  margin: 0;
}

.setup-card__steps {
  padding: 1rem 2rem;
  border-bottom: 1px solid var(--border);
}

.setup-card__body {
  padding: 2rem;
}

/* Step transition */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.slide-up-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
