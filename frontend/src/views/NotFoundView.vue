<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="not-found">
    <p class="code">404</p>
    <h1>Page Not Found</h1>
    <p class="desc">The page you are looking for does not exist.</p>
    <RouterLink to="/" class="home-link">Back to home</RouterLink>
  </div>
</template>

<style scoped>
.not-found {
  text-align: center;
  padding-top: 5rem;
}

.code {
  font-size: 5rem;
  font-weight: 800;
  color: #374151;
  line-height: 1;
  margin-bottom: 0.5rem;
}

h1 {
  font-size: 1.5rem;
  color: #f3f4f6;
  margin-bottom: 0.5rem;
}

.desc {
  color: #6b7280;
  margin-bottom: 1.5rem;
}

.home-link {
  display: inline-block;
  padding: 0.5rem 1.25rem;
  background: #f97316;
  color: #fff;
  border-radius: 6px;
  text-decoration: none;
  font-weight: 600;
}

.home-link:hover {
  background: #ea6c0a;
}
</style>
