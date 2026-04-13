<template>
  <div id="mirofish-app">
    <header class="top-bar">
      <div class="logo">
        <span class="logo-icon">&#9670;</span>
        <span class="logo-text">MiroFish</span>
        <span class="logo-sub">Claude</span>
      </div>
      <div class="controls">
        <select v-model="selectedGraphId" class="graph-select">
          <option value="">Select graph...</option>
          <option v-for="p in projects" :key="p.id" :value="p.graph_id">
            {{ p.name || p.id }}
          </option>
        </select>
        <button class="btn-refresh" @click="refresh" :disabled="!selectedGraphId">
          &#8635; Refresh
        </button>
      </div>
      <div class="stats" v-if="graphStats">
        <span class="stat"><b>{{ graphStats.nodes }}</b> nodes</span>
        <span class="stat-sep">|</span>
        <span class="stat"><b>{{ graphStats.edges }}</b> edges</span>
        <span class="stat-sep">|</span>
        <span class="stat"><b>{{ graphStats.types }}</b> types</span>
      </div>
    </header>

    <main class="graph-area">
      <div v-if="!selectedGraphId" class="empty-state">
        <div class="empty-icon">&#9670;</div>
        <h2>No graph loaded</h2>
        <p>Run simulation from CLI, then select graph above.</p>
        <p class="empty-hint">Or open with <code>?graph=GRAPH_ID</code> in URL</p>
      </div>
      <GraphPanel
        v-else
        :graphId="selectedGraphId"
        :refreshTrigger="refreshCount"
        @nodeClick="onNodeClick"
        @edgeClick="onEdgeClick"
      />
    </main>

    <aside class="info-bar" v-if="selectedProject">
      <div class="info-section">
        <h4>Project</h4>
        <p>{{ selectedProject.name || selectedProject.id }}</p>
        <span class="badge" :class="selectedProject.status?.toLowerCase()">
          {{ selectedProject.status }}
        </span>
      </div>
      <div v-if="selectedProject.ontology" class="info-section">
        <h4>Entity Types</h4>
        <div class="tag-list">
          <span
            v-for="(et, i) in (selectedProject.ontology.entity_types || [])"
            :key="et.name"
            class="tag"
            :style="{ borderColor: COLORS[i % COLORS.length] }"
          >{{ et.name }}</span>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import GraphPanel from './components/GraphPanel.vue'
import { listProjects, getProject } from './api/graph.js'

const COLORS = [
  '#FF5722', '#2196F3', '#4CAF50', '#FFC107', '#9C27B0',
  '#00BCD4', '#FF9800', '#E91E63', '#3F51B5', '#009688',
]

const projects = ref([])
const selectedGraphId = ref('')
const selectedProject = ref(null)
const refreshCount = ref(0)

const graphStats = computed(() => {
  if (!selectedProject.value) return null
  const ont = selectedProject.value.ontology
  return {
    nodes: selectedProject.value.nodes_count || '?',
    edges: selectedProject.value.edges_count || '?',
    types: ont?.entity_types?.length || '?',
  }
})

function refresh() {
  refreshCount.value++
}

function onNodeClick(node) {
  // detail handled by GraphPanel internally
}

function onEdgeClick(edge) {
  // detail handled by GraphPanel internally
}

async function loadProjects() {
  try {
    const resp = await listProjects()
    projects.value = resp.data || resp || []
    // Auto-select if URL has ?graph=xxx
    const params = new URLSearchParams(window.location.search)
    const graphParam = params.get('graph')
    if (graphParam) {
      selectedGraphId.value = graphParam
    } else if (projects.value.length > 0) {
      const latest = projects.value[0]
      if (latest.graph_id) {
        selectedGraphId.value = latest.graph_id
      }
    }
  } catch {
    projects.value = []
  }
}

watch(selectedGraphId, async (graphId) => {
  if (!graphId) {
    selectedProject.value = null
    return
  }
  const proj = projects.value.find((p) => p.graph_id === graphId)
  if (proj) {
    try {
      const resp = await getProject(proj.id)
      selectedProject.value = resp.data || resp
    } catch {
      selectedProject.value = proj
    }
  }
})

// Auto-refresh every 30s when a graph is loaded
let autoRefresh = null
watch(selectedGraphId, (id) => {
  if (autoRefresh) clearInterval(autoRefresh)
  if (id) {
    autoRefresh = setInterval(() => { refreshCount.value++ }, 30000)
  }
})

onMounted(() => {
  loadProjects()
})
</script>

<style>
/* -- Reset -- */
*, *::before, *::after {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --bg-page: #0a0a0a;
  --bg-card: #1a1a1a;
  --bg-input: #111111;
  --text-primary: #e0e0e0;
  --text-secondary: #888888;
  --accent: #FF5722;
  --accent-hover: #E64A19;
  --border: #2a2a2a;
  --border-active: #FF5722;
  --font-mono: 'JetBrains Mono', monospace;
  --font-heading: 'Space Grotesk', sans-serif;
  --font-body: 'Inter', sans-serif;
  --radius: 8px;
  --transition: 0.2s ease;
}

html, body {
  background: var(--bg-page);
  color: var(--text-primary);
  font-family: var(--font-mono);
  line-height: 1.6;
  height: 100%;
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
}

#app { height: 100%; }

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-page); }
::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #555; }
</style>

<style scoped>
#mirofish-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: relative;
}

/* Top bar */
.top-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  z-index: 20;
}

.logo {
  display: flex;
  align-items: center;
  gap: 6px;
}

.logo-icon {
  color: var(--accent);
  font-size: 18px;
}

.logo-text {
  font-family: var(--font-heading);
  font-weight: 700;
  font-size: 16px;
}

.logo-sub {
  font-size: 11px;
  color: var(--text-secondary);
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
}

.controls {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.graph-select {
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 10px;
  font-family: var(--font-mono);
  font-size: 12px;
  min-width: 200px;
  cursor: pointer;
}

.graph-select:focus {
  border-color: var(--accent);
  outline: none;
}

.btn-refresh {
  background: transparent;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 6px;
  padding: 5px 12px;
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition);
}

.btn-refresh:hover { background: rgba(255,87,34,0.1); }
.btn-refresh:disabled { opacity: 0.3; cursor: not-allowed; }

.stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.stat b { color: var(--text-primary); }
.stat-sep { color: var(--border); }

/* Main graph area */
.graph-area {
  flex: 1;
  position: relative;
  overflow: hidden;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 10px;
  color: var(--text-secondary);
}

.empty-icon {
  font-size: 48px;
  color: var(--border);
  margin-bottom: 8px;
}

.empty-state h2 {
  font-family: var(--font-heading);
  font-size: 20px;
  color: var(--text-primary);
}

.empty-state p { font-size: 14px; }

.empty-hint {
  margin-top: 8px;
  font-size: 12px;
}

.empty-hint code {
  background: var(--bg-card);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}

/* Info sidebar (right) */
.info-bar {
  position: absolute;
  top: 48px;
  right: 0;
  width: 240px;
  max-height: calc(100vh - 60px);
  overflow-y: auto;
  padding: 12px;
  background: rgba(26, 26, 26, 0.92);
  border-left: 1px solid var(--border);
  z-index: 15;
}

.info-section {
  margin-bottom: 16px;
}

.info-section h4 {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.info-section p {
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.badge {
  display: inline-block;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.badge.graph_completed { background: #1B5E20; color: #A5D6A7; }
.badge.ontology_generated { background: #E65100; color: #FFB74D; }
.badge.created { background: #1A237E; color: #9FA8DA; }
.badge.failed { background: #B71C1C; color: #EF9A9A; }

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tag {
  font-size: 10px;
  padding: 2px 8px;
  border: 1px solid;
  border-radius: 10px;
  color: var(--text-primary);
}
</style>
