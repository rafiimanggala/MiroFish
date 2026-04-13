<template>
  <div class="graph-panel" ref="containerRef">
    <div v-if="isLoading" class="graph-state">
      <div class="spinner-lg" />
      <p>Loading graph data...</p>
    </div>

    <div v-else-if="!graphNodes.length" class="graph-state">
      <p class="empty-label">No graph data available</p>
    </div>

    <template v-else>
      <svg ref="svgRef" class="graph-svg" />

      <div class="graph-legend">
        <div
          v-for="(color, type) in entityColorMap"
          :key="type"
          class="legend-item"
        >
          <span class="legend-dot" :style="{ background: color }" />
          <span class="legend-label">{{ type }}</span>
        </div>
      </div>

      <transition name="detail-fade">
        <div v-if="selectedNode" class="detail-overlay" @click.self="clearSelection">
          <div class="detail-card">
            <button class="detail-close" @click="clearSelection">x</button>
            <h3 class="detail-title">{{ selectedNode.name || selectedNode.label || selectedNode.id }}</h3>
            <span class="detail-type-badge" :style="{ background: getNodeColor(selectedNode) }">
              {{ selectedNode.entity_type || 'Unknown' }}
            </span>
            <div v-if="selectedNode.summary" class="detail-section">
              <p class="detail-label">Summary</p>
              <p class="detail-text">{{ selectedNode.summary }}</p>
            </div>
            <div v-if="selectedNode.attributes && Object.keys(selectedNode.attributes).length" class="detail-section">
              <p class="detail-label">Attributes</p>
              <div class="detail-attrs">
                <div v-for="(val, key) in selectedNode.attributes" :key="key" class="attr-row">
                  <span class="attr-key">{{ key }}</span>
                  <span class="attr-val">{{ val }}</span>
                </div>
              </div>
            </div>
            <p class="detail-connections">{{ getConnectionCount(selectedNode) }} connections</p>
          </div>
        </div>
      </transition>

      <transition name="detail-fade">
        <div v-if="selectedEdge" class="detail-overlay" @click.self="clearSelection">
          <div class="detail-card">
            <button class="detail-close" @click="clearSelection">x</button>
            <div class="edge-flow">
              <span class="edge-source">{{ getEdgeNodeName(selectedEdge, 'source') }}</span>
              <span class="edge-arrow">→</span>
              <span class="edge-type-label">{{ selectedEdge.edge_type || selectedEdge.type || 'related' }}</span>
              <span class="edge-arrow">→</span>
              <span class="edge-target">{{ getEdgeNodeName(selectedEdge, 'target') }}</span>
            </div>
            <div v-if="selectedEdge.fact || selectedEdge.description" class="detail-section">
              <p class="detail-label">Fact</p>
              <p class="detail-text">{{ selectedEdge.fact || selectedEdge.description }}</p>
            </div>
          </div>
        </div>
      </transition>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as d3 from 'd3'
import { getGraphData } from '../api/graph.js'

const COLORS = [
  '#FF5722', '#2196F3', '#4CAF50', '#FFC107', '#9C27B0',
  '#00BCD4', '#FF9800', '#E91E63', '#3F51B5', '#009688',
]

const props = defineProps({
  graphId: { type: String, default: '' },
  refreshTrigger: { type: Number, default: 0 },
})

const emit = defineEmits(['nodeClick', 'edgeClick'])

const containerRef = ref(null)
const svgRef = ref(null)
const isLoading = ref(false)
const graphNodes = ref([])
const graphEdges = ref([])
const selectedNode = ref(null)
const selectedEdge = ref(null)

let simulation = null
let resizeObserver = null

const entityColorMap = computed(() => {
  const map = {}
  const types = [...new Set(graphNodes.value.map((n) => n.entity_type || 'Unknown'))]
  types.forEach((type, i) => {
    map[type] = COLORS[i % COLORS.length]
  })
  return map
})

function getNodeColor(node) {
  const type = node.entity_type || 'Unknown'
  return entityColorMap.value[type] || COLORS[0]
}

function getConnectionCount(node) {
  return graphEdges.value.filter(
    (e) => (e.source?.id || e.source) === node.id || (e.target?.id || e.target) === node.id
  ).length
}

function getEdgeNodeName(edge, side) {
  const nodeRef = edge[side]
  const id = typeof nodeRef === 'object' ? nodeRef.id : nodeRef
  const node = graphNodes.value.find((n) => n.id === id)
  return node?.name || node?.label || id || 'Unknown'
}

function clearSelection() {
  selectedNode.value = null
  selectedEdge.value = null
}

async function fetchData() {
  if (!props.graphId) return
  isLoading.value = true
  clearSelection()

  try {
    const resp = await getGraphData(props.graphId)
    const gd = resp.data || resp
    graphNodes.value = (gd.nodes || []).map((n) => ({
      ...n,
      entity_type: n.entity_type || n.type,
    }))
    graphEdges.value = (gd.edges || gd.links || []).map((e) => ({
      ...e,
      edge_type: e.edge_type || e.type,
    }))
    isLoading.value = false
    await nextTick()
    renderGraph()
  } catch {
    graphNodes.value = []
    graphEdges.value = []
    isLoading.value = false
  }
}

function renderGraph() {
  if (!svgRef.value || !graphNodes.value.length) return

  const container = containerRef.value
  const width = container.clientWidth
  const height = container.clientHeight || 500

  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()
  svg.attr('width', width).attr('height', height)

  // Defs for arrowheads and glow
  const defs = svg.append('defs')

  defs.append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 22)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#555')

  const glowFilter = defs.append('filter')
    .attr('id', 'glow')
    .attr('x', '-50%').attr('y', '-50%')
    .attr('width', '200%').attr('height', '200%')
  glowFilter.append('feGaussianBlur')
    .attr('stdDeviation', '3')
    .attr('result', 'blur')
  const feMerge = glowFilter.append('feMerge')
  feMerge.append('feMergeNode').attr('in', 'blur')
  feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

  const g = svg.append('g')

  const zoom = d3.zoom()
    .scaleExtent([0.1, 6])
    .on('zoom', (event) => g.attr('transform', event.transform))
  svg.call(zoom)

  const nodes = graphNodes.value.map((n) => ({ ...n }))
  const nodeNames = new Set(nodes.map((n) => n.name || n.id))
  const links = graphEdges.value
    .map((e) => ({ ...e }))
    .filter((e) => nodeNames.has(e.source) && nodeNames.has(e.target))

  if (simulation) simulation.stop()

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id((d) => d.name || d.id).distance(100))
    .force('charge', d3.forceManyBody().strength(-250))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius((d) => getNodeRadius(d) + 4))

  // Edges
  const linkGroup = g.append('g').attr('class', 'links')

  const link = linkGroup.selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', '#444')
    .attr('stroke-width', 1.2)
    .attr('stroke-opacity', 0.5)
    .attr('marker-end', 'url(#arrowhead)')
    .attr('cursor', 'pointer')
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedNode.value = null
      selectedEdge.value = d
      emit('edgeClick', d)
    })

  const linkLabel = linkGroup.selectAll('text')
    .data(links)
    .join('text')
    .text((d) => d.edge_type || d.type || '')
    .attr('font-size', 9)
    .attr('fill', '#666')
    .attr('text-anchor', 'middle')
    .attr('pointer-events', 'none')

  // Nodes
  const nodeGroup = g.append('g').attr('class', 'nodes')

  const nodeCircle = nodeGroup.selectAll('circle')
    .data(nodes)
    .join('circle')
    .attr('r', (d) => getNodeRadius(d))
    .attr('fill', (d) => getNodeColor(d))
    .attr('stroke', '#111')
    .attr('stroke-width', 1.5)
    .attr('cursor', 'pointer')
    .on('mouseover', function () {
      d3.select(this).attr('filter', 'url(#glow)')
    })
    .on('mouseout', function () {
      d3.select(this).attr('filter', null)
    })
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedEdge.value = null
      selectedNode.value = d
      emit('nodeClick', d)
    })
    .call(d3.drag()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null
        d.fy = null
      }))

  const nodeLabel = nodeGroup.selectAll('text')
    .data(nodes)
    .join('text')
    .text((d) => d.name || d.label || d.id)
    .attr('font-size', 10)
    .attr('fill', '#aaa')
    .attr('dx', (d) => getNodeRadius(d) + 4)
    .attr('dy', 4)
    .attr('pointer-events', 'none')

  // Click SVG background to deselect
  svg.on('click', () => {
    clearSelection()
  })

  simulation.on('tick', () => {
    link
      .attr('x1', (d) => d.source.x)
      .attr('y1', (d) => d.source.y)
      .attr('x2', (d) => d.target.x)
      .attr('y2', (d) => d.target.y)

    linkLabel
      .attr('x', (d) => (d.source.x + d.target.x) / 2)
      .attr('y', (d) => (d.source.y + d.target.y) / 2 - 6)

    nodeCircle
      .attr('cx', (d) => d.x)
      .attr('cy', (d) => d.y)

    nodeLabel
      .attr('x', (d) => d.x)
      .attr('y', (d) => d.y)
  })
}

function getNodeRadius(node) {
  const connections = graphEdges.value.filter(
    (e) => (e.source?.id || e.source) === node.id || (e.target?.id || e.target) === node.id
  ).length
  return Math.max(6, Math.min(18, 6 + connections * 1.5))
}

function handleResize() {
  if (graphNodes.value.length > 0) {
    renderGraph()
  }
}

watch(() => props.graphId, () => {
  fetchData()
})

watch(() => props.refreshTrigger, () => {
  fetchData()
})

onMounted(() => {
  fetchData()

  if (containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      handleResize()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  if (simulation) simulation.stop()
  if (resizeObserver) resizeObserver.disconnect()
})
</script>

<style scoped>
.graph-panel {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 400px;
  background: #111;
  overflow: hidden;
}

.graph-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 14px;
}

.spinner-lg {
  width: 28px;
  height: 28px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-label {
  color: var(--text-secondary);
}

.graph-svg {
  display: block;
  width: 100%;
  height: 100%;
}

/* Legend */
.graph-legend {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(10, 10, 10, 0.85);
  border: 1px solid var(--border);
  border-radius: 6px;
  max-width: 320px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* Detail overlay */
.detail-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 16px;
  background: rgba(0, 0, 0, 0.4);
  z-index: 10;
}

.detail-card {
  width: 320px;
  max-height: 80%;
  overflow-y: auto;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  position: relative;
}

.detail-close {
  position: absolute;
  top: 10px;
  right: 12px;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 16px;
  cursor: pointer;
  transition: color var(--transition);
}

.detail-close:hover {
  color: var(--accent);
}

.detail-title {
  font-family: var(--font-heading);
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-right: 24px;
}

.detail-type-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  margin-bottom: 16px;
}

.detail-section {
  margin-bottom: 14px;
}

.detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.detail-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
}

.detail-attrs {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.attr-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  padding: 4px 8px;
  background: var(--bg-input);
  border-radius: 4px;
}

.attr-key {
  color: var(--text-secondary);
  font-weight: 500;
}

.attr-val {
  color: var(--text-primary);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}

.detail-connections {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 8px;
}

/* Edge detail */
.edge-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.edge-source,
.edge-target {
  font-family: var(--font-heading);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.edge-arrow {
  color: var(--accent);
  font-size: 16px;
}

.edge-type-label {
  padding: 2px 10px;
  background: rgba(255, 87, 34, 0.15);
  color: var(--accent);
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

/* Transitions */
.detail-fade-enter-active,
.detail-fade-leave-active {
  transition: opacity 0.2s ease;
}

.detail-fade-enter-from,
.detail-fade-leave-to {
  opacity: 0;
}
</style>
