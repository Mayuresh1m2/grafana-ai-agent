<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import {
  VueFlow,
  useVueFlow,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type Connection,
  type NodeMouseEvent,
  type EdgeMouseEvent,
} from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

import {
  fetchGraph,
  saveGraph,
  NODE_TYPES,
  EDGE_TYPES,
  NODE_TYPE_LABELS,
  EDGE_TYPE_LABELS,
  type NodeType,
  type EdgeType,
  type GraphNode,
  type GraphEdge,
} from '@/api/serviceGraph'

// ── Vue Flow instance ─────────────────────────────────────────────────────────
const { addNodes, addEdges, onConnect, fitView, removeNodes, removeEdges } = useVueFlow()

// ── State ─────────────────────────────────────────────────────────────────────
const nodes    = ref<Node[]>([])
const edges    = ref<Edge[]>([])
const loading  = ref(false)
const saving   = ref(false)
const error    = ref<string | null>(null)
const saved    = ref(false)

// Selection / properties panel
const selectedNode = ref<Node | null>(null)
const selectedEdge = ref<Edge | null>(null)

// Drag-from-palette state
const dragNodeType = ref<NodeType | null>(null)

// ── Node type styling ─────────────────────────────────────────────────────────
const NODE_COLORS: Record<NodeType, { bg: string; border: string; text: string }> = {
  service:  { bg: '#1e3a2f', border: '#2d5a3f', text: '#6ee7b7' },
  topic:    { bg: '#3b2000', border: '#7c4a00', text: '#fbbf24' },
  queue:    { bg: '#2d2510', border: '#6b5420', text: '#fcd34d' },
  database: { bg: '#1e2a3a', border: '#2d4a6a', text: '#93c5fd' },
  external: { bg: '#2a2a2a', border: '#4a4a4a', text: '#d1d5db' },
}

const NODE_ICONS: Record<NodeType, string> = {
  service:  '⬡',
  topic:    '⊡',
  queue:    '▤',
  database: '⊟',
  external: '⬚',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeVfNode(gn: GraphNode): Node {
  const colors = NODE_COLORS[gn.node_type]
  return {
    id:       gn.id,
    type:     'default',
    position: { x: gn.position_x, y: gn.position_y },
    style: {
      background:   colors.bg,
      border:       `1px solid ${colors.border}`,
      borderRadius: '8px',
      color:        colors.text,
      padding:      '10px 14px',
      minWidth:     '130px',
    },
    data: {
      label:       `${NODE_ICONS[gn.node_type]} ${gn.name}`,
      node_type:   gn.node_type,
      name:        gn.name,
      description: gn.description,
      tech:        gn.tech,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  }
}

function makeVfEdge(ge: GraphEdge): Edge {
  return {
    id:          ge.id,
    source:      ge.source,
    target:      ge.target,
    label:       ge.label || EDGE_TYPE_LABELS[ge.edge_type],
    animated:    ge.edge_type === 'publish' || ge.edge_type === 'subscribe',
    markerEnd:   MarkerType.ArrowClosed,
    style:       { stroke: '#6b7280' },
    labelStyle:  { fill: '#9ca3af', fontSize: '11px' },
    labelBgStyle:{ fill: '#1f2937', fillOpacity: 0.8 },
    data: {
      edge_type: ge.edge_type,
      label:     ge.label,
    },
  }
}

function toGraphNode(n: Node): GraphNode {
  return {
    id:          n.id,
    node_type:   n.data.node_type as NodeType,
    name:        n.data.name as string,
    description: n.data.description as string ?? '',
    tech:        n.data.tech as string ?? '',
    position_x:  n.position.x,
    position_y:  n.position.y,
  }
}

function toGraphEdge(e: Edge): GraphEdge {
  return {
    id:        e.id,
    source:    e.source,
    target:    e.target,
    edge_type: (e.data?.edge_type as EdgeType) ?? 'rest',
    label:     (e.data?.label as string) ?? '',
  }
}

// ── Load ──────────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  error.value   = null
  try {
    const graph  = await fetchGraph()
    nodes.value  = graph.nodes.map(makeVfNode)
    edges.value  = graph.edges.map(makeVfEdge)
    await nextTick()
    fitView({ padding: 0.2 })
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
    await saveGraph(nodes.value.map(toGraphNode), edges.value.map(toGraphEdge))
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } catch (e) {
    error.value = String(e)
  } finally {
    saving.value = false
  }
}

// ── Connections ───────────────────────────────────────────────────────────────
onConnect((params: Connection) => {
  const newEdge: Edge = {
    id:        `e-${Date.now()}`,
    source:    params.source,
    target:    params.target,
    label:     EDGE_TYPE_LABELS['rest'],
    animated:  false,
    markerEnd: MarkerType.ArrowClosed,
    style:     { stroke: '#6b7280' },
    labelStyle:  { fill: '#9ca3af', fontSize: '11px' },
    labelBgStyle:{ fill: '#1f2937', fillOpacity: 0.8 },
    data: { edge_type: 'rest', label: '' },
  }
  edges.value = [...edges.value, newEdge]
  // Auto-select the new edge for editing
  selectedEdge.value = newEdge
  selectedNode.value = null
})

// ── Selection ─────────────────────────────────────────────────────────────────
function onNodeClick({ node }: NodeMouseEvent) {
  selectedNode.value = node
  selectedEdge.value = null
}

function onEdgeClick({ edge }: EdgeMouseEvent) {
  selectedEdge.value = edge
  selectedNode.value = null
}

function clearSelection() {
  selectedNode.value = null
  selectedEdge.value = null
}

// ── Node properties edit ──────────────────────────────────────────────────────
function updateSelectedNode(field: string, value: string) {
  if (!selectedNode.value) return
  const idx = nodes.value.findIndex(n => n.id === selectedNode.value!.id)
  if (idx === -1) return
  const n = { ...nodes.value[idx]! }
  n.data = { ...n.data, [field]: value }
  if (field === 'name' || field === 'node_type') {
    const type = (field === 'node_type' ? value : n.data.node_type) as NodeType
    const name = field === 'name' ? value : n.data.name as string
    const colors = NODE_COLORS[type]
    n.data = { ...n.data, label: `${NODE_ICONS[type]} ${name}`, node_type: type }
    n.style = {
      ...n.style,
      background: colors.bg,
      border:     `1px solid ${colors.border}`,
      color:      colors.text,
    }
  }
  nodes.value = [...nodes.value.slice(0, idx), n, ...nodes.value.slice(idx + 1)]
  selectedNode.value = n
}

// ── Edge properties edit ──────────────────────────────────────────────────────
function updateSelectedEdge(field: string, value: string) {
  if (!selectedEdge.value) return
  const idx = edges.value.findIndex(e => e.id === selectedEdge.value!.id)
  if (idx === -1) return
  const e = { ...edges.value[idx]! }
  e.data = { ...e.data, [field]: value }
  if (field === 'edge_type') {
    const et = value as EdgeType
    e.label    = (e.data.label as string) || EDGE_TYPE_LABELS[et]
    e.animated = et === 'publish' || et === 'subscribe'
  }
  if (field === 'label') {
    e.label = value || EDGE_TYPE_LABELS[e.data.edge_type as EdgeType]
  }
  edges.value = [...edges.value.slice(0, idx), e, ...edges.value.slice(idx + 1)]
  selectedEdge.value = e
}

// ── Delete ────────────────────────────────────────────────────────────────────
function deleteSelected() {
  if (selectedNode.value) {
    removeNodes([selectedNode.value.id])
    nodes.value = nodes.value.filter(n => n.id !== selectedNode.value!.id)
    edges.value = edges.value.filter(e => e.source !== selectedNode.value!.id && e.target !== selectedNode.value!.id)
    selectedNode.value = null
  } else if (selectedEdge.value) {
    removeEdges([selectedEdge.value.id])
    edges.value = edges.value.filter(e => e.id !== selectedEdge.value!.id)
    selectedEdge.value = null
  }
}

// ── Drag-to-canvas from palette ───────────────────────────────────────────────
function onPaletteDragStart(type: NodeType, evt: DragEvent) {
  dragNodeType.value = type
  evt.dataTransfer?.setData('application/vueflow-node-type', type)
}

function onCanvasDrop(evt: DragEvent) {
  evt.preventDefault()
  const type = (evt.dataTransfer?.getData('application/vueflow-node-type') as NodeType) ?? dragNodeType.value
  if (!type) return

  const canvas = (evt.currentTarget as HTMLElement).getBoundingClientRect()
  const x = evt.clientX - canvas.left
  const y = evt.clientY - canvas.top

  const newNode: Node = makeVfNode({
    id:          `node-${Date.now()}`,
    node_type:   type,
    name:        NODE_TYPE_LABELS[type],
    description: '',
    tech:        '',
    position_x:  x,
    position_y:  y,
  })

  nodes.value = [...nodes.value, newNode]
  selectedNode.value = newNode
  selectedEdge.value = null
  dragNodeType.value = null
}

function onCanvasDragOver(evt: DragEvent) {
  evt.preventDefault()
  if (evt.dataTransfer) evt.dataTransfer.dropEffect = 'copy'
}

// ── Computed helpers for properties panel ─────────────────────────────────────
const panelNode = computed(() => selectedNode.value?.data)
const panelEdge = computed(() => selectedEdge.value?.data)
</script>

<template>
  <div class="sg-page">

    <!-- ── Toolbar ─────────────────────────────────────────────────────────── -->
    <header class="sg-toolbar">
      <div class="sg-toolbar__left">
        <h1 class="sg-title">Service Graph</h1>
        <span class="sg-subtitle">
          {{ nodes.length }} node{{ nodes.length !== 1 ? 's' : '' }},
          {{ edges.length }} edge{{ edges.length !== 1 ? 's' : '' }}
        </span>
      </div>
      <div class="sg-toolbar__right">
        <span v-if="error" class="sg-error">{{ error }}</span>
        <button
          v-if="selectedNode || selectedEdge"
          class="btn-danger"
          title="Delete selected (Del)"
          @click="deleteSelected"
        >Delete</button>
        <button class="btn-ghost" @click="fitView({ padding: 0.2 })">Fit</button>
        <button
          class="btn-primary"
          :disabled="saving"
          @click="save"
        >
          {{ saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save' }}
        </button>
      </div>
    </header>

    <div class="sg-body">

      <!-- ── Node palette ────────────────────────────────────────────────── -->
      <aside class="sg-palette">
        <p class="sg-palette__title">Drag to add</p>
        <div
          v-for="type in NODE_TYPES"
          :key="type"
          class="sg-palette__item"
          draggable="true"
          @dragstart="onPaletteDragStart(type, $event)"
        >
          <span class="sg-palette__icon" :style="{ color: NODE_COLORS[type].text }">
            {{ NODE_ICONS[type] }}
          </span>
          <span class="sg-palette__label">{{ NODE_TYPE_LABELS[type] }}</span>
        </div>

        <p class="sg-palette__hint">
          Drag a node onto the canvas, then connect handles to create edges.
          Click any node or edge to edit its properties.
        </p>
      </aside>

      <!-- ── Canvas ─────────────────────────────────────────────────────── -->
      <div
        class="sg-canvas"
        @drop="onCanvasDrop"
        @dragover="onCanvasDragOver"
      >
        <div v-if="loading" class="sg-loading">Loading…</div>
        <VueFlow
          v-else
          v-model:nodes="nodes"
          v-model:edges="edges"
          class="sg-flow"
          :default-zoom="1"
          :min-zoom="0.2"
          :max-zoom="4"
          fit-view-on-init
          @node-click="onNodeClick"
          @edge-click="onEdgeClick"
          @pane-click="clearSelection"
        >
          <!-- Mini-map / controls slots could go here -->
        </VueFlow>
      </div>

      <!-- ── Properties panel ───────────────────────────────────────────── -->
      <Transition name="panel-slide">
        <aside v-if="selectedNode || selectedEdge" class="sg-props">

          <!-- Node properties -->
          <template v-if="selectedNode && panelNode">
            <p class="sg-props__title">Node</p>

            <label class="prop-field">
              <span class="prop-label">Name</span>
              <input
                class="prop-input"
                :value="panelNode.name"
                @input="updateSelectedNode('name', ($event.target as HTMLInputElement).value)"
              />
            </label>

            <label class="prop-field">
              <span class="prop-label">Type</span>
              <select
                class="prop-input"
                :value="panelNode.node_type"
                @change="updateSelectedNode('node_type', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="t in NODE_TYPES" :key="t" :value="t">{{ NODE_TYPE_LABELS[t] }}</option>
              </select>
            </label>

            <label class="prop-field">
              <span class="prop-label">Tech</span>
              <input
                class="prop-input"
                :value="panelNode.tech"
                placeholder="Python/FastAPI, Kafka…"
                @input="updateSelectedNode('tech', ($event.target as HTMLInputElement).value)"
              />
            </label>

            <label class="prop-field">
              <span class="prop-label">Description</span>
              <textarea
                class="prop-input"
                rows="3"
                :value="panelNode.description"
                placeholder="What does this do?"
                @input="updateSelectedNode('description', ($event.target as HTMLTextAreaElement).value)"
              />
            </label>

            <button class="btn-danger prop-delete" @click="deleteSelected">Delete node</button>
          </template>

          <!-- Edge properties -->
          <template v-else-if="selectedEdge && panelEdge">
            <p class="sg-props__title">Edge</p>

            <label class="prop-field">
              <span class="prop-label">Interaction</span>
              <select
                class="prop-input"
                :value="panelEdge.edge_type"
                @change="updateSelectedEdge('edge_type', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="t in EDGE_TYPES" :key="t" :value="t">{{ EDGE_TYPE_LABELS[t] }}</option>
              </select>
            </label>

            <label class="prop-field">
              <span class="prop-label">Label <span class="hint">(optional)</span></span>
              <input
                class="prop-input"
                :value="panelEdge.label"
                placeholder="e.g. order-created"
                @input="updateSelectedEdge('label', ($event.target as HTMLInputElement).value)"
              />
            </label>

            <button class="btn-danger prop-delete" @click="deleteSelected">Delete edge</button>
          </template>

        </aside>
      </Transition>

    </div><!-- .sg-body -->
  </div>
</template>

<style scoped>
/* ── Page shell ──────────────────────────────────────────────────────────── */
.sg-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
}

/* ── Toolbar ─────────────────────────────────────────────────────────────── */
.sg-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
  gap: 1rem;
}
.sg-toolbar__left  { display: flex; align-items: baseline; gap: 0.75rem; }
.sg-toolbar__right { display: flex; align-items: center;   gap: 0.5rem; }

.sg-title    { font-size: 1rem; font-weight: 700; margin: 0; }
.sg-subtitle { font-size: 0.78rem; color: var(--text-muted); }
.sg-error    { font-size: 0.8rem; color: var(--status-error); }

/* ── Body (palette | canvas | panel) ─────────────────────────────────────── */
.sg-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Node palette ─────────────────────────────────────────────────────────── */
.sg-palette {
  width: 148px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--surface);
  padding: 0.75rem 0.6rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  overflow-y: auto;
}
.sg-palette__title {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0 0 0.25rem;
}
.sg-palette__item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: grab;
  background: var(--surface-2);
  user-select: none;
  transition: border-color 0.12s, background 0.12s;
}
.sg-palette__item:hover {
  border-color: var(--accent-blue);
  background: var(--surface-3, var(--surface-2));
}
.sg-palette__item:active { cursor: grabbing; }

.sg-palette__icon  { font-size: 1.1rem; }
.sg-palette__label { font-size: 0.78rem; color: var(--text); }

.sg-palette__hint {
  font-size: 0.7rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}

/* ── Canvas ──────────────────────────────────────────────────────────────── */
.sg-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
}
.sg-flow  { width: 100%; height: 100%; }
.sg-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 0.9rem;
}

/* ── Properties panel ────────────────────────────────────────────────────── */
.sg-props {
  width: 220px;
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--surface);
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  overflow-y: auto;
}
.sg-props__title {
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0;
}

.prop-field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.prop-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-weight: 500;
}
.prop-label .hint { font-weight: 400; opacity: 0.7; }
.prop-input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.4rem 0.6rem;
  font-size: 0.82rem;
  color: var(--text);
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
}
.prop-input:focus { outline: none; border-color: var(--accent-blue); }

.prop-delete { margin-top: auto; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.btn-primary {
  background: var(--accent-blue);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  padding: 0.4rem 1rem;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.12s;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-ghost {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: var(--radius);
  padding: 0.4rem 0.75rem;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.btn-ghost:hover { background: var(--surface-2); color: var(--text); }

.btn-danger {
  background: none;
  border: 1px solid var(--status-error, #ef4444);
  color: var(--status-error, #ef4444);
  border-radius: var(--radius);
  padding: 0.4rem 0.75rem;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.12s;
  width: 100%;
}
.btn-danger:hover { background: rgba(239,68,68,0.12); }

/* ── Panel slide transition ──────────────────────────────────────────────── */
.panel-slide-enter-active,
.panel-slide-leave-active { transition: width 0.18s ease, opacity 0.18s ease; }
.panel-slide-enter-from,
.panel-slide-leave-to     { width: 0; opacity: 0; padding: 0; overflow: hidden; }

/* ── Vue Flow dark-mode overrides ───────────────────────────────────────── */
:deep(.vue-flow__background) { background: var(--bg, #111827); }
:deep(.vue-flow__controls)   { background: var(--surface); border-color: var(--border); }
:deep(.vue-flow__minimap)    { background: var(--surface); }
:deep(.vue-flow__edge-path)  { stroke: #6b7280; }
:deep(.vue-flow__edge-text)  { fill: #9ca3af; }
</style>
