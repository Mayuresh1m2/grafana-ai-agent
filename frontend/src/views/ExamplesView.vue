<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createExample,
  deleteExample,
  fetchExamples,
  detectPlaceholders,
  QUERY_CATEGORIES,
  CATEGORY_LABELS,
  type ExampleCreate,
  type QueryCategory,
  type QueryExample,
} from '@/api/examples'
import { useSessionStore } from '@/stores/sessionStore'

const session = useSessionStore()

// ── State ─────────────────────────────────────────────────────────────────────
const examples       = ref<QueryExample[]>([])
const loading        = ref(false)
const error          = ref<string | null>(null)
const showForm       = ref(false)
const saving         = ref(false)
const activeCategory = ref<QueryCategory | 'all'>('all')

// ── Form fields ───────────────────────────────────────────────────────────────
const form = ref<ExampleCreate>({
  title:        '',
  description:  '',
  query_type:   'loki',
  category:     'service',
  template:     '',
  tags:         [],
  placeholders: [],
})
const tagsInput = ref('')

// Auto-detect any {{key}} placeholders present in the template
const detectedPlaceholders = computed<string[]>(() => detectPlaceholders(form.value.template))

// Filtered list based on selected category tab
const filteredExamples = computed(() =>
  activeCategory.value === 'all'
    ? examples.value
    : examples.value.filter(e => e.category === activeCategory.value)
)

// ── Load ──────────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  error.value   = null
  try {
    examples.value = await fetchExamples(session.grafanaUrl)
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

// ── Save ──────────────────────────────────────────────────────────────────────
async function save() {
  saving.value = true
  error.value  = null
  try {
    form.value.tags         = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean)
    form.value.placeholders = detectedPlaceholders.value
    await createExample(form.value, session.grafanaUrl)
    showForm.value = false
    resetForm()
    await load()
  } catch (e) {
    error.value = String(e)
  } finally {
    saving.value = false
  }
}

function placeholder(key: string): string {
  return `\u007b\u007b${key}\u007d\u007d`
}

function resetForm() {
  form.value  = { title: '', description: '', query_type: 'loki', category: 'service', template: '', tags: [], placeholders: [] }
  tagsInput.value = ''
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function remove(id: string) {
  if (!confirm('Delete this example?')) return
  try {
    await deleteExample(id, session.grafanaUrl)
    examples.value = examples.value.filter(e => e.id !== id)
  } catch (e) {
    error.value = String(e)
  }
}
</script>

<template>
  <div class="examples-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">Query Examples</h1>
        <p class="page-subtitle">Curated LogQL / PromQL templates — retrieved at query time and injected into the agent prompt.</p>
      <p v-if="session.grafanaUrl" class="page-instance">Instance: <code>{{ session.grafanaUrl }}</code></p>
      </div>
      <button class="btn-primary" @click="showForm = !showForm">
        {{ showForm ? 'Cancel' : '+ Add Example' }}
      </button>
    </header>

    <!-- Add form -->
    <Transition name="slide">
      <form v-if="showForm" class="example-form" @submit.prevent="save">
        <h2 class="form-title">New Query Example</h2>

        <div class="form-row">
          <label class="field">
            <span class="field-label">Title</span>
            <input v-model="form.title" class="field-input" placeholder="Error logs for a service" required />
          </label>
          <label class="field field--sm">
            <span class="field-label">Type</span>
            <select v-model="form.query_type" class="field-input">
              <option value="loki">Loki (LogQL)</option>
              <option value="prometheus">Prometheus (PromQL)</option>
            </select>
          </label>
          <label class="field field--sm">
            <span class="field-label">Category</span>
            <select v-model="form.category" class="field-input">
              <option v-for="cat in QUERY_CATEGORIES" :key="cat" :value="cat">{{ CATEGORY_LABELS[cat] }}</option>
            </select>
          </label>
        </div>

        <label class="field">
          <span class="field-label">Description <span class="hint">(this text is embedded for semantic search)</span></span>
          <textarea v-model="form.description" class="field-input" rows="2"
            placeholder="Retrieves error-level logs for a specific application in a given namespace" required />
        </label>

        <label class="field">
          <span class="field-label">Query Template</span>
          <textarea v-model="form.template" class="field-input field-input--mono" rows="4"
            placeholder='{app="{{app}}", namespace="{{namespace}}"} |= "error" | logfmt' required />
        </label>

        <!-- Auto-detected placeholders -->
        <div v-if="detectedPlaceholders.length" class="placeholder-chips">
          <span class="chips-label">Detected placeholders:</span>
          <span v-for="p in detectedPlaceholders" :key="p" class="chip">{{ placeholder(p) }}</span>
        </div>

        <label class="field">
          <span class="field-label">Tags <span class="hint">(comma-separated)</span></span>
          <input v-model="tagsInput" class="field-input" placeholder="errors, kubernetes, logs" />
        </label>

        <p v-if="error" class="form-error">{{ error }}</p>

        <div class="form-actions">
          <button type="button" class="btn-ghost" @click="showForm = false; resetForm()">Cancel</button>
          <button type="submit" class="btn-primary" :disabled="saving">
            {{ saving ? 'Saving…' : 'Save Example' }}
          </button>
        </div>
      </form>
    </Transition>

    <!-- Error -->
    <p v-if="error && !showForm" class="page-error">{{ error }}</p>

    <!-- Category filter tabs -->
    <div v-if="!loading && examples.length" class="filter-tabs">
      <button
        :class="['filter-tab', activeCategory === 'all' && 'filter-tab--active']"
        @click="activeCategory = 'all'"
      >All</button>
      <button
        v-for="cat in QUERY_CATEGORIES"
        :key="cat"
        :class="['filter-tab', activeCategory === cat && 'filter-tab--active']"
        @click="activeCategory = cat"
      >{{ CATEGORY_LABELS[cat] }}</button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-state">Loading…</div>

    <!-- Empty -->
    <div v-else-if="!examples.length && !showForm" class="empty-state">
      <p>No examples yet.</p>
      <p class="hint">Add your first working query so the agent can use it as a template.</p>
    </div>

    <!-- Empty filter result -->
    <div v-else-if="!filteredExamples.length" class="empty-state">
      <p>No examples for this category.</p>
    </div>

    <!-- List -->
    <ul v-else class="example-list">
      <li v-for="ex in filteredExamples" :key="ex.id" class="example-card">
        <div class="example-header">
          <span :class="['type-badge', `type-badge--${ex.query_type}`]">{{ ex.query_type }}</span>
          <span :class="['cat-badge', `cat-badge--${ex.category}`]">{{ CATEGORY_LABELS[ex.category] }}</span>
          <span class="example-title">{{ ex.title }}</span>
          <button class="btn-delete" title="Delete" @click="remove(ex.id)">✕</button>
        </div>
        <p class="example-desc">{{ ex.description }}</p>
        <pre class="example-template">{{ ex.template }}</pre>
        <div class="example-footer">
          <span v-for="tag in ex.tags" :key="tag" class="tag">{{ tag }}</span>
          <span v-for="p in ex.placeholders" :key="p" class="chip chip--sm">{{ placeholder(p) }}</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.examples-page { max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem; }

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.page-title    { font-size: 1.3rem; font-weight: 700; margin: 0 0 0.25rem; }
.page-subtitle { font-size: 0.85rem; color: var(--text-muted); margin: 0; }
.page-instance { font-size: 0.78rem; color: var(--text-muted); margin: 0.25rem 0 0; }
.page-instance code { font-family: var(--font-mono); font-size: 0.78rem; }
.page-error    { color: var(--status-error); font-size: 0.85rem; }

/* ── Form ── */
.example-form {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}
.form-title  { font-size: 1rem; font-weight: 600; margin: 0 0 1.25rem; }
.form-row    { display: grid; grid-template-columns: 1fr auto auto; gap: 1rem; }
.field       { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 1rem; }
.field--sm   { min-width: 160px; }
.field-label { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
.hint        { font-weight: 400; opacity: 0.7; }
.field-input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  color: var(--text);
  width: 100%;
  box-sizing: border-box;
}
.field-input--mono { font-family: var(--font-mono); font-size: 0.8rem; }
.field-input:focus { outline: none; border-color: var(--accent-blue); }

.placeholder-chips { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.chips-label { font-size: 0.78rem; color: var(--text-muted); }

.form-error   { color: var(--status-error); font-size: 0.85rem; margin-bottom: 0.75rem; }
.form-actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 0.5rem; }

/* ── List ── */
.empty-state { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.example-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }

.example-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1rem 1.25rem;
}
.example-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }
.example-title  { font-size: 0.95rem; font-weight: 600; flex: 1; }
.example-desc   { font-size: 0.83rem; color: var(--text-muted); margin: 0 0 0.75rem; }
.example-template {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.6rem 0.8rem;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0 0 0.75rem;
}
.example-footer { display: flex; flex-wrap: wrap; gap: 0.4rem; }

/* ── Filter tabs ── */
.filter-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 1rem;
}
.filter-tab {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.25rem 0.75rem;
  font-size: 0.78rem;
  color: var(--text-muted);
  cursor: pointer;
}
.filter-tab:hover { background: var(--surface-2); color: var(--text); }
.filter-tab--active { background: var(--accent-blue); border-color: var(--accent-blue); color: #fff; }

.type-badge {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.type-badge--loki       { background: #1e3a5f; color: #60a5fa; }
.type-badge--prometheus { background: #3b1f1f; color: #f87171; }

.cat-badge {
  font-size: 0.68rem;
  font-weight: 500;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  text-transform: capitalize;
}
.cat-badge--service        { background: #1e3a2f; color: #6ee7b7; }
.cat-badge--database       { background: #2d2510; color: #fbbf24; }
.cat-badge--infrastructure { background: #1e2a3a; color: #93c5fd; }
.cat-badge--kubernetes     { background: #2a1e3a; color: #c4b5fd; }
.cat-badge--networking     { background: #1e3030; color: #67e8f9; }

.tag {
  font-size: 0.72rem;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.chip {
  font-size: 0.72rem;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: #1e3a2f;
  border: 1px solid #2d5a3f;
  color: #6ee7b7;
  font-family: var(--font-mono);
}
.chip--sm { font-size: 0.68rem; }

.btn-delete {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 0.8rem;
  padding: 0.2rem 0.4rem;
  border-radius: var(--radius);
}
.btn-delete:hover { color: var(--status-error); background: var(--surface-2); }
.btn-ghost {
  background: none;
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: var(--radius);
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  cursor: pointer;
}
.btn-ghost:hover { background: var(--surface-2); }
.btn-primary {
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

/* Transition */
.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
