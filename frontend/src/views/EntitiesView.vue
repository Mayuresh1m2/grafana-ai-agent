<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createEntity,
  deleteEntity,
  fetchEntities,
  ENTITY_TYPES,
  ENTITY_TYPE_LABELS,
  type EntityCreate,
  type EntityType,
  type ServiceEntity,
} from '@/api/entities'

// ── State ─────────────────────────────────────────────────────────────────────
const entities      = ref<ServiceEntity[]>([])
const loading       = ref(false)
const error         = ref<string | null>(null)
const showForm      = ref(false)
const saving        = ref(false)
const filterType    = ref<EntityType | 'all'>('all')

// ── Form fields ───────────────────────────────────────────────────────────────
const form = ref<EntityCreate>({
  name:        '',
  namespace:   '',
  entity_type: 'service',
  aliases:     [],
  description: '',
})
const aliasesInput = ref('')

const filteredEntities = computed(() =>
  filterType.value === 'all'
    ? entities.value
    : entities.value.filter(e => e.entity_type === filterType.value)
)

// ── Load ──────────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  error.value   = null
  try {
    entities.value = await fetchEntities()
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
    form.value.aliases = aliasesInput.value
      .split(',')
      .map(a => a.trim())
      .filter(Boolean)
    await createEntity(form.value)
    showForm.value = false
    resetForm()
    await load()
  } catch (e) {
    error.value = String(e)
  } finally {
    saving.value = false
  }
}

function resetForm() {
  form.value     = { name: '', namespace: '', entity_type: 'service', aliases: [], description: '' }
  aliasesInput.value = ''
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function remove(id: string) {
  if (!confirm('Delete this entity?')) return
  try {
    await deleteEntity(id)
    entities.value = entities.value.filter(e => e.id !== id)
  } catch (e) {
    error.value = String(e)
  }
}
</script>

<template>
  <div class="entities-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">Service Entities</h1>
        <p class="page-subtitle">
          Map natural-language names to exact service names and namespaces.
          When your query mentions an alias, the agent receives the canonical name automatically.
        </p>
      </div>
      <button class="btn-primary" @click="showForm = !showForm">
        {{ showForm ? 'Cancel' : '+ Add Entity' }}
      </button>
    </header>

    <!-- Add form -->
    <Transition name="slide">
      <form v-if="showForm" class="entity-form" @submit.prevent="save">
        <h2 class="form-title">New Service Entity</h2>

        <div class="form-row-3">
          <label class="field">
            <span class="field-label">Canonical name <span class="hint">(exact k8s name)</span></span>
            <input v-model="form.name" class="field-input field-input--mono"
              placeholder="reporting-processor" required />
          </label>
          <label class="field">
            <span class="field-label">Namespace</span>
            <input v-model="form.namespace" class="field-input field-input--mono"
              placeholder="prod-services" required />
          </label>
          <label class="field field--sm">
            <span class="field-label">Type</span>
            <select v-model="form.entity_type" class="field-input">
              <option v-for="t in ENTITY_TYPES" :key="t" :value="t">{{ ENTITY_TYPE_LABELS[t] }}</option>
            </select>
          </label>
        </div>

        <label class="field">
          <span class="field-label">Aliases <span class="hint">(comma-separated — what users might say)</span></span>
          <input v-model="aliasesInput" class="field-input"
            placeholder="reporting, reports, report service, reporting pipeline" required />
        </label>

        <label class="field">
          <span class="field-label">Description <span class="hint">(optional)</span></span>
          <input v-model="form.description" class="field-input"
            placeholder="Processes and aggregates reporting events" />
        </label>

        <p v-if="error" class="form-error">{{ error }}</p>

        <div class="form-actions">
          <button type="button" class="btn-ghost" @click="showForm = false; resetForm()">Cancel</button>
          <button type="submit" class="btn-primary" :disabled="saving">
            {{ saving ? 'Saving…' : 'Save Entity' }}
          </button>
        </div>
      </form>
    </Transition>

    <!-- Error -->
    <p v-if="error && !showForm" class="page-error">{{ error }}</p>

    <!-- Filter tabs -->
    <div v-if="!loading && entities.length" class="filter-tabs">
      <button :class="['filter-tab', filterType === 'all' && 'filter-tab--active']"
        @click="filterType = 'all'">All</button>
      <button v-for="t in ENTITY_TYPES" :key="t"
        :class="['filter-tab', filterType === t && 'filter-tab--active']"
        @click="filterType = t">{{ ENTITY_TYPE_LABELS[t] }}</button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-state">Loading…</div>

    <!-- Empty -->
    <div v-else-if="!entities.length && !showForm" class="empty-state">
      <p>No entities yet.</p>
      <p class="hint">Add your first entity so the agent can resolve "reporting" → "reporting-processor".</p>
    </div>

    <!-- Empty filter -->
    <div v-else-if="!filteredEntities.length" class="empty-state">
      <p>No entities for this type.</p>
    </div>

    <!-- List -->
    <ul v-else class="entity-list">
      <li v-for="en in filteredEntities" :key="en.id" class="entity-card">
        <div class="entity-header">
          <span :class="['type-badge', `type-badge--${en.entity_type}`]">
            {{ ENTITY_TYPE_LABELS[en.entity_type] }}
          </span>
          <span class="entity-name">{{ en.name }}</span>
          <span class="entity-ns">{{ en.namespace }}</span>
          <button class="btn-delete" title="Delete" @click="remove(en.id)">✕</button>
        </div>
        <p v-if="en.description" class="entity-desc">{{ en.description }}</p>
        <div class="entity-aliases">
          <span class="aliases-label">Aliases:</span>
          <span v-for="alias in en.aliases" :key="alias" class="alias-chip">{{ alias }}</span>
          <span v-if="!en.aliases.length" class="hint">none</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.entities-page { max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem; }

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.page-title    { font-size: 1.3rem; font-weight: 700; margin: 0 0 0.25rem; }
.page-subtitle { font-size: 0.85rem; color: var(--text-muted); margin: 0; max-width: 560px; }
.page-error    { color: var(--status-error); font-size: 0.85rem; }

/* ── Form ── */
.entity-form {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}
.form-title    { font-size: 1rem; font-weight: 600; margin: 0 0 1.25rem; }
.form-row-3    { display: grid; grid-template-columns: 1fr 1fr auto; gap: 1rem; }
.field         { display: flex; flex-direction: column; gap: 0.35rem; margin-bottom: 1rem; }
.field--sm     { min-width: 140px; }
.field-label   { font-size: 0.8rem; font-weight: 500; color: var(--text-muted); }
.hint          { font-weight: 400; opacity: 0.7; }
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
.field-input--mono { font-family: var(--font-mono); }
.field-input:focus { outline: none; border-color: var(--accent-blue); }
.form-error    { color: var(--status-error); font-size: 0.85rem; margin-bottom: 0.75rem; }
.form-actions  { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 0.5rem; }

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

/* ── List ── */
.empty-state  { text-align: center; padding: 3rem 1rem; color: var(--text-muted); }
.entity-list  { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }

.entity-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1rem 1.25rem;
}
.entity-header {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.5rem;
  flex-wrap: wrap;
}
.entity-name {
  font-family: var(--font-mono);
  font-size: 0.9rem;
  font-weight: 600;
  flex: 1;
}
.entity-ns {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--text-muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.1rem 0.45rem;
}
.entity-desc {
  font-size: 0.83rem;
  color: var(--text-muted);
  margin: 0 0 0.6rem;
}
.entity-aliases {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.aliases-label {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.alias-chip {
  font-size: 0.72rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: #1e2a3a;
  border: 1px solid #2a3f5a;
  color: #93c5fd;
  font-style: italic;
}

.type-badge {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  text-transform: capitalize;
}
.type-badge--service    { background: #1e3a2f; color: #6ee7b7; }
.type-badge--namespace  { background: #2d2510; color: #fbbf24; }
.type-badge--database   { background: #3b1f1f; color: #f87171; }
.type-badge--deployment { background: #2a1e3a; color: #c4b5fd; }

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

.slide-enter-active, .slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
