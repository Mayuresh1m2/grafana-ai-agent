<script setup lang="ts">
import { ref, onMounted, onUnmounted, provide } from 'vue'
import { RouterView, useRoute } from 'vue-router'

// ── Theme ─────────────────────────────────────────────────────────────────────
const theme = ref<'dark' | 'light'>(
  (localStorage.getItem('theme') as 'dark' | 'light') ?? 'dark'
)
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
  localStorage.setItem('theme', theme.value)
  document.documentElement.dataset['theme'] = theme.value
}
onMounted(() => {
  document.documentElement.dataset['theme'] = theme.value
})

// ── Network banner ────────────────────────────────────────────────────────────
const networkOffline = ref(!navigator.onLine)
const networkHandler = () => { networkOffline.value = !navigator.onLine }
onMounted(() => {
  window.addEventListener('online',  networkHandler)
  window.addEventListener('offline', networkHandler)
})
onUnmounted(() => {
  window.removeEventListener('online',  networkHandler)
  window.removeEventListener('offline', networkHandler)
})

// ── Error boundary ────────────────────────────────────────────────────────────
const fatalError = ref<string | null>(null)
provide('reportFatalError', (msg: string) => { fatalError.value = msg })

const route = useRoute()
const isSetup = () => route.name === 'setup'
</script>

<template>
  <div class="app-shell" :class="{ 'full-height': !isSetup() }">

    <!-- Network offline banner -->
    <Transition name="slide-down">
      <div v-if="networkOffline" class="network-banner" role="alert">
        <span class="network-icon">⚠</span>
        Network offline — reconnecting…
      </div>
    </Transition>

    <!-- Fatal error overlay -->
    <div v-if="fatalError" class="fatal-overlay">
      <div class="fatal-card">
        <div class="fatal-icon">💥</div>
        <h2>Something went wrong</h2>
        <p>{{ fatalError }}</p>
        <button class="btn-primary" @click="fatalError = null; $router.push('/setup')">
          Start over
        </button>
      </div>
    </div>

    <!-- Header -->
    <header class="app-header">
      <div class="app-nav">
        <span class="nav-brand">
          <span class="brand-icon">◈</span>
          Grafana AI Agent
        </span>
        <div class="nav-right">
          <button
            class="theme-toggle btn-reset"
            :aria-label="`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`"
            :title="`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`"
            @click="toggleTheme"
          >
            {{ theme === 'dark' ? '☀' : '🌙' }}
          </button>
        </div>
      </div>
    </header>

    <!-- Main content (no padding for chat — it manages its own layout) -->
    <main class="app-main">
      <RouterView />
    </main>

  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.app-shell.full-height { height: 100vh; overflow: hidden; }

/* ── Network banner ─────────────────────────────────────────────────────────── */
.network-banner {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 1000;
  background: var(--status-warn);
  color: #000;
  font-size: 0.85rem;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.4rem 1rem;
}
.network-icon { font-size: 1rem; }

/* ── Fatal overlay ──────────────────────────────────────────────────────────── */
.fatal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.75);
  z-index: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}
.fatal-card {
  background: var(--surface);
  border: 1px solid var(--status-error);
  border-radius: var(--radius-lg);
  padding: 2rem;
  max-width: 420px;
  text-align: center;
  box-shadow: var(--shadow-lg);
}
.fatal-icon { font-size: 2.5rem; margin-bottom: 1rem; }
.fatal-card h2 { font-size: 1.15rem; margin-bottom: 0.5rem; }
.fatal-card p  { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.25rem; }

/* ── Header ─────────────────────────────────────────────────────────────────── */
.app-header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 1.25rem;
  flex-shrink: 0;
  z-index: 10;
}
.app-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--header-height);
}
.nav-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--accent-blue);
  letter-spacing: -0.01em;
  user-select: none;
}
.brand-icon { font-size: 1.1rem; opacity: 0.9; }
.nav-right  { display: flex; align-items: center; gap: 0.75rem; }

.theme-toggle {
  font-size: 1.1rem;
  width: 32px; height: 32px;
  border-radius: var(--radius);
  display: flex; align-items: center; justify-content: center;
  transition: background var(--t);
  color: var(--text-muted);
}
.theme-toggle:hover { background: var(--surface-2); color: var(--text); }

/* ── Main ───────────────────────────────────────────────────────────────────── */
.app-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* ── Primary button ─────────────────────────────────────────────────────────── */
.btn-primary {
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  padding: 0.6rem 1.25rem;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--t);
}
.btn-primary:hover { background: var(--accent-blue-hover); }

/* ── Transitions ────────────────────────────────────────────────────────────── */
.slide-down-enter-active,
.slide-down-leave-active { transition: transform var(--t-md), opacity var(--t-md); }
.slide-down-enter-from,
.slide-down-leave-to    { transform: translateY(-100%); opacity: 0; }
</style>
