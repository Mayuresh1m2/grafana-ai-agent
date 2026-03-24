<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <nav class="app-nav" aria-label="Main navigation">
        <RouterLink to="/" class="nav-brand" aria-label="Grafana AI Agent — home">
          Grafana AI Agent
        </RouterLink>
        <RouterLink to="/chat" class="nav-link">Chat</RouterLink>
      </nav>
    </header>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style>
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  background: #111827;
  color: #e5e7eb;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  font-size: 15px;
  line-height: 1.6;
}

a {
  color: inherit;
}
</style>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  background: #1f2937;
  border-bottom: 1px solid #374151;
  padding: 0 1.5rem;
}

.app-nav {
  display: flex;
  align-items: center;
  gap: 2rem;
  height: 56px;
}

.nav-brand {
  font-size: 1rem;
  font-weight: 700;
  color: #f97316;
  text-decoration: none;
  letter-spacing: -0.02em;
}

.nav-link {
  color: #9ca3af;
  text-decoration: none;
  font-size: 0.9rem;
  transition: color 0.15s;
}

.nav-link:hover,
.nav-link.router-link-active {
  color: #f3f4f6;
}

.app-main {
  flex: 1;
  padding: 1.5rem;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
}
</style>
