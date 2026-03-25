<script setup lang="ts">
defineProps<{ message?: string }>()
</script>

<template>
  <div class="net-banner" role="alert">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
      <path d="M8 5v3.5M8 11h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    <span>{{ message ?? 'You are offline. Reconnecting…' }}</span>
  </div>
</template>

<style scoped>
.net-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: rgba(255, 179, 71, 0.12);
  border-bottom: 1px solid rgba(255, 179, 71, 0.3);
  color: var(--status-warn);
  font-size: 0.85rem;
}
</style>
