<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="home">
    <div class="hero">
      <h1 class="hero-title">Grafana AI Agent</h1>
      <p class="hero-subtitle">
        Ask natural-language questions about your metrics, logs, and traces. Powered by a local LLM
        via Ollama — your data never leaves your infrastructure.
      </p>
      <RouterLink to="/chat" class="cta-btn">Start chatting</RouterLink>
    </div>

    <section class="features">
      <div class="feature-card">
        <span class="feature-icon">📊</span>
        <h2>Metrics</h2>
        <p>Query Prometheus with natural language and understand PromQL results instantly.</p>
      </div>
      <div class="feature-card">
        <span class="feature-icon">📋</span>
        <h2>Logs</h2>
        <p>Search and summarise Loki log streams without writing LogQL by hand.</p>
      </div>
      <div class="feature-card">
        <span class="feature-icon">🔍</span>
        <h2>Traces</h2>
        <p>Analyse distributed traces from Tempo and pinpoint latency bottlenecks.</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home {
  padding-top: 3rem;
}

.hero {
  text-align: center;
  max-width: 640px;
  margin: 0 auto 4rem;
}

.hero-title {
  font-size: 2.25rem;
  font-weight: 800;
  color: #f3f4f6;
  letter-spacing: -0.03em;
  margin-bottom: 1rem;
}

.hero-subtitle {
  color: #9ca3af;
  font-size: 1.05rem;
  line-height: 1.7;
  margin-bottom: 2rem;
}

.cta-btn {
  display: inline-block;
  padding: 0.7rem 2rem;
  background: #f97316;
  color: #fff;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 600;
  font-size: 0.95rem;
  transition: background 0.15s;
}

.cta-btn:hover {
  background: #ea6c0a;
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1.25rem;
}

.feature-card {
  background: #1f2937;
  border: 1px solid #374151;
  border-radius: 10px;
  padding: 1.5rem;
}

.feature-icon {
  font-size: 1.75rem;
  display: block;
  margin-bottom: 0.75rem;
}

.feature-card h2 {
  font-size: 1rem;
  font-weight: 700;
  color: #f3f4f6;
  margin-bottom: 0.4rem;
}

.feature-card p {
  color: #9ca3af;
  font-size: 0.875rem;
  line-height: 1.6;
}
</style>
